"""Milestone 2: SSRF-safe "Auto-Detect ATS" probe for the dashboard watchlist.

Input: a careers / ATS board URL or "platform:slug". Detection never trusts the URL as a fetch target
for the board itself: the slug is extracted and the jobs are read ONLY from the fixed public ATS API
hosts (boards-api.greenhouse.io, api.lever.co, api.ashbyhq.com, api.smartrecruiters.com) through the
watchers' existing fetchers. A non-ATS careers page is scanned for an embedded board link only after:
  * `validate_public_https` (feed_clients/validation: https, no credentials, port 443, no private /
    reserved IP literal, no .local/.internal hosts);
  * every DNS answer for the host is a global address (no rebinding into the LAN / metadata IPs);
  * one GET with redirects disabled, a 512 KiB body cap and an 8 s timeout.
The sample is evaluated against the CURRENT portal rules + candidate preferences (no LLM).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from backend.app.browser_v2.adapters.feed_clients.http import ConditionalHttp
from backend.app.browser_v2.adapters.feed_clients.validation import PublicHTTPSURL
from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    CandidatePreferences,
    PortalRules,
    evaluate_pipeline,
)
from backend.app.browser_v2.watchers.sources import (
    ashby_fetcher,
    greenhouse_fetcher,
    lever_fetcher,
)

SLUG = r"[A-Za-z0-9_-]{1,100}"
PAIR = re.compile(rf"^\s*(greenhouse|lever|ashby|smartrecruiters)\s*:\s*({SLUG})\s*$", re.IGNORECASE)
HOSTS: dict[str, str] = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse", "job-boards.eu.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse", "jobs.lever.co": "lever", "jobs.eu.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby", "careers.smartrecruiters.com": "smartrecruiters",
    "jobs.smartrecruiters.com": "smartrecruiters",
}
EMBEDDED = re.compile(
    rf"https?://(?:(?:job-)?boards(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?for=(?P<gh_embed>{SLUG})"
    rf"|(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?P<gh>{SLUG})"
    rf"|jobs(?:\.eu)?\.lever\.co/(?P<lever>{SLUG})"
    rf"|jobs\.ashbyhq\.com/(?P<ashby>{SLUG})"
    rf"|(?:careers|jobs)\.smartrecruiters\.com/(?P<sr>{SLUG}))", re.IGNORECASE)
RESERVED_SEGMENTS = frozenset({"embed", "v1", "jobs", "api", "job_board"})
BOARD_URLS = {"greenhouse": "https://job-boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}",
              "ashby": "https://jobs.ashbyhq.com/{}", "smartrecruiters": "https://careers.smartrecruiters.com/{}"}
PAGE_MAX_BYTES = 512 * 1024
PAGE_TIMEOUT = 8.0
SAMPLE_SIZE = 8
_URL: TypeAdapter[Any] = TypeAdapter(PublicHTTPSURL)
Resolver = Callable[[str], Awaitable[list[str]]]
PageFetcher = Callable[[str], Awaitable[str]]


class ProbeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BoardRef:
    platform: str
    slug: str

    @property
    def board_url(self) -> str:
        return BOARD_URLS[self.platform].format(self.slug)


def safe_public_url(target: str) -> str:
    """The SSRF gate for any owner-pasted URL (raises ProbeError on scheme / credential / private host)."""
    try:
        return str(_URL.validate_python(target.strip()))
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "invalid URL") if exc.errors() else "invalid URL"
        raise ProbeError("unsafe_url", str(message).removeprefix("Value error, ")) from None


def board_from_url(url: str) -> BoardRef | None:
    parts = urlsplit(url)
    platform = HOSTS.get((parts.hostname or "").lower())
    if platform is None:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if platform == "greenhouse" and segments[:1] == ["embed"]:
        embed = (parse_qs(parts.query).get("for") or [""])[0]
        return BoardRef(platform, embed) if re.fullmatch(SLUG, embed) else None
    if (parts.hostname or "").lower() == "boards-api.greenhouse.io":
        segments = segments[2:] if segments[:2] == ["v1", "boards"] else []
    slug = next((s for s in segments if s.lower() not in RESERVED_SEGMENTS), None)
    return BoardRef(platform, slug) if slug and re.fullmatch(SLUG, slug) else None


def board_from_html(html: str) -> BoardRef | None:
    match = EMBEDDED.search(html or "")
    if match is None:
        return None
    for group, platform in (("gh_embed", "greenhouse"), ("gh", "greenhouse"), ("lever", "lever"),
                            ("ashby", "ashby"), ("sr", "smartrecruiters")):
        slug = match.group(group)
        if slug and slug.lower() not in RESERVED_SEGMENTS:
            return BoardRef(platform, slug)
    return None


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


async def guarded_page(url: str, *, resolver: Resolver = system_resolver,
                       client: httpx.AsyncClient | None = None) -> str:
    host = urlsplit(url).hostname or ""
    try:
        addresses = await resolver(host)
    except OSError:
        raise ProbeError("dns_failed", "The careers page host does not resolve") from None
    if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise ProbeError("unsafe_url", "The careers page resolves to a private or reserved address")
    owns = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, timeout=PAGE_TIMEOUT)
    try:
        async with client.stream("GET", url, headers={"Accept": "text/html"}) as response:
            if response.status_code != 200:
                raise ProbeError("page_unavailable", f"The careers page answered HTTP {response.status_code}")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > PAGE_MAX_BYTES:
                    break
        return body[:PAGE_MAX_BYTES].decode("utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise ProbeError("page_unavailable", f"The careers page could not be read ({type(exc).__name__})") from None
    finally:
        if owns:
            await client.aclose()


async def detect_board(target: str, *, page_fetcher: PageFetcher | None = None) -> BoardRef:
    pair = PAIR.match(target or "")
    if pair:
        return BoardRef(pair.group(1).lower(), pair.group(2))
    url = safe_public_url(target)
    ref = board_from_url(url)
    if ref is not None:
        return ref
    html = await (page_fetcher or guarded_page)(url)
    ref = board_from_html(html)
    if ref is None:
        raise ProbeError("ats_not_detected", "No Greenhouse, Lever, Ashby or SmartRecruiters board was found")
    return ref


async def fetch_board_jobs(ref: BoardRef, http: ConditionalHttp, client: httpx.AsyncClient) -> list[FeedJob]:
    """Jobs from the FIXED public ATS API host only (never the pasted URL)."""
    if ref.platform == "smartrecruiters":
        result = await http.get(f"https://api.smartrecruiters.com/v1/companies/{ref.slug}/postings",
                                params={"limit": 100})
        data = json.loads(result.body or b"{}")
        jobs = []
        for item in (data.get("content") or [])[:200] if isinstance(data, dict) else []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            location = item.get("location") or {}
            jobs.append(FeedJob(external_job_id=str(item.get("id") or ""), title=str(item["name"])[:300],
                                url=f"https://jobs.smartrecruiters.com/{ref.slug}/{item.get('id')}",
                                company=ref.slug, apply_url=None,
                                location=", ".join(str(location[k]) for k in ("city", "country")
                                                   if isinstance(location, dict) and location.get(k)) or None))
        return jobs
    factory = {"greenhouse": greenhouse_fetcher, "lever": lever_fetcher, "ashby": ashby_fetcher}[ref.platform]
    fetched = await factory(ref.slug, None)(http, client, None)
    return list(fetched.jobs or [])


def evaluate(job: FeedJob, rules: PortalRules, prefs: CandidatePreferences, now: datetime) -> tuple[bool, list[str]]:
    posted = job.posted_at
    age = None if posted is None else max((now - (posted if posted.tzinfo else posted.replace(tzinfo=UTC))).days, 0)
    verdict = evaluate_pipeline(age_days=age, applicants=UNKNOWN_APPLICANTS, rules=rules, prefs=prefs,
                                title=job.title, company=job.company, description=job.description,
                                salary_text=job.salary_text, work_mode=job.work_mode, require_description=False)
    return verdict.passed, list(verdict.reasons)


async def probe(target: str, *, rules: PortalRules, preferences: Mapping[str, Any],
                client: httpx.AsyncClient | None = None, page_fetcher: PageFetcher | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    ref = await detect_board(target, page_fetcher=page_fetcher)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=False)
    try:
        jobs = await fetch_board_jobs(ref, ConditionalHttp(client, min_interval=0), client)
    except ProbeError:
        raise
    except Exception as exc:  # noqa: BLE001 - unknown board / provider error -> a clean 422 upstream
        raise ProbeError("board_unavailable", f"The {ref.platform} board '{ref.slug}' could not be read "
                                              f"({type(exc).__name__})") from None
    finally:
        if owns:
            await client.aclose()
    moment = now or datetime.now(UTC)
    prefs = CandidatePreferences.from_profile({"preferences": dict(preferences)})
    evaluated = [(job, *evaluate(job, rules, prefs, moment)) for job in jobs]
    matched = [row for row in evaluated if row[1]]
    sample = (matched + [row for row in evaluated if not row[1]])[:SAMPLE_SIZE]
    watched = preferences.get(f"{ref.platform}_boards")
    return {"platform": ref.platform, "slug": ref.slug, "board_url": ref.board_url, "job_count": len(jobs),
            "matched_count": len(matched),
            "sample": [{"title": job.title or "Untitled", "location": job.location, "url": job.url,
                        "passes": passes, "reasons": reasons[:5]} for job, passes, reasons in sample],
            "already_watched": isinstance(watched, (dict, list)) and ref.slug in watched}
