"""Base for API/RSS-discovered portals whose application lives on a hosted ATS form.

Discovery is a zero-login public read (no browser), cached in memory so `inspect_job`
needs no second request. Inspection opens the hosted Greenhouse/Lever form in the
worker tab (closed postings and CAPTCHAs are detected before any click); unknown
external ATS links are classified `external_unsupported_ats:<host>` (FILTERED_OUT),
never guessed at. Apply is delegated to `HostedAtsApplier`.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    HitlQuestion,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.adapters.challenge import CHALLENGE_HELPERS_JS
from backend.app.browser_v2.adapters.common import (
    SUPPORTED_ATS,
    HostedAtsApplier,
    HostedFormFiller,
    age_days_from,
    ats_form_url,
    classify_ats,
    form_state,
    role_query_match,
)
from backend.app.browser_v2.answers import CandidateFacts, ScreeningResolver
from backend.app.browser_v2.forms import extract_form
from backend.app.browser_v2.rules import UNKNOWN_APPLICANTS
from backend.app.browser_v2.state import ApplicationState, guard_apply

S = ApplicationState
CACHE_LIMIT = 500
FEED_TTL_SEC = 30 * 60
USER_AGENT = "automated-apply/2 (+personal job search; low volume)"


# Public ATS boards return the WHOLE board in one response (live 2026-11-26: stripe = 772 jobs /
# 6 MB; palantir lever > 200) while the legacy sources slice it 100 per page and re-download
# per page. Read up to 8 pages from ONE memoized download.
PAGE_SIZE = 100
MAX_PAGES = 8


class MemoTransport(httpx.AsyncBaseTransport):
    """Serve repeated GETs of one URL from memory (one board download per fetch, not per page)."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.cache: dict[str, tuple[int, list[tuple[str, str]], bytes]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if request.method == "GET" and key in self.cache:
            status, headers, body = self.cache[key]
            return httpx.Response(status, headers=headers, content=body, request=request)
        response = await self.inner.handle_async_request(request)
        if request.method != "GET":
            return response
        body = await response.aread()
        await response.aclose()
        headers = [(k, v) for k, v in response.headers.multi_items()
                   if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
        self.cache[key] = (response.status_code, headers, body)
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def fetch_all_pages(source: Any, call: Callable[[int, int], Any], *, page_size: int = PAGE_SIZE,
                          max_pages: int = MAX_PAGES) -> list[Any]:
    jobs: list[Any] = []
    for page in range(1, max_pages + 1):
        batch = await call(page_size, page)
        jobs.extend(batch)
        if not getattr(source, "next_cursor", None) or len(batch) < page_size:
            break
    return jobs


APPLY_LINK_JS = r"""
() => {
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const links = [...document.querySelectorAll("a[href]")].filter(visible)
    .filter(a => /apply/i.test((a.innerText || "").trim()) || a.id === "job-cta-alt" || a.id === "job-cta-alt-2");
  return links.map(a => a.href).filter(h => /^https:\/\//.test(h)).slice(0, 3);
}
"""
PAGE_CHALLENGE_JS = "() => {" + CHALLENGE_HELPERS_JS + """
  const body = ((document.body && document.body.innerText) || "").slice(0, 20000);
  return challengeNodes() || challengeText(body);
}"""


class ApplyLinkChallenge(RuntimeError):
    """A bot challenge (e.g. Cloudflare "Just a moment...") blocked resolving the employer apply link."""


class ApplyLinkLoginWall(RuntimeError):
    """The listing hides the employer link behind the portal's own account wall.

    Live 2026-11-26: weworkremotely.com "Apply now" -> /job-seekers/account/register?alert=Create an
    account to view full job details.
    """


class PortalWallActive(RuntimeError):
    """This portal hit a login/challenge wall recently: leave the job untouched (backlog) this cycle."""


PORTAL_WALL_TTL_SEC = 30 * 60
ACCOUNT_WALL_PATH = re.compile(r"/(?:[a-z-]*/)?(?:account/)?(?:register|sign[_-]?up|sign[_-]?in|log[_-]?in)\b",
                               re.IGNORECASE)


async def page_challenged(page: Any) -> bool:
    try:
        return bool(await page.evaluate(PAGE_CHALLENGE_JS))
    except Exception:  # noqa: BLE001 - an unreadable page is not proof of a challenge
        return False


async def external_apply_link(page: Any, url: str, origin_hosts: frozenset[str], *, settle_ms: int) -> str | None:
    """Open a listing page in the worker tab and return its first off-site Apply link.

    Raises ApplyLinkChallenge when the page is a bot interstitial (fail closed: CAPTCHA HITL,
    never a terminal `external_unsupported_ats` FILTERED_OUT).
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(settle_ms)
    if await page_challenged(page):
        raise ApplyLinkChallenge(urlsplit(url).hostname or "unknown")
    on_site_walls = 0
    for href in await page.evaluate(APPLY_LINK_JS):
        absolute = urljoin(url, href)
        parts = urlsplit(absolute)
        if (parts.hostname or "") not in origin_hosts:
            return absolute
        on_site_walls += bool(ACCOUNT_WALL_PATH.search(parts.path))
    if on_site_walls:
        raise ApplyLinkLoginWall(urlsplit(url).hostname or "unknown")
    return None


@dataclass(frozen=True)
class FeedJob:
    external_job_id: str
    url: str  # canonical posting URL (stored as applications.job_url)
    title: str | None
    company: str | None
    apply_url: str | None
    description: str | None = None
    posted_at: datetime | None = None
    location: str | None = None
    salary_text: str | None = None
    work_mode: str | None = None


class FeedAdapter:
    platform = "feed"
    attribution: str | None = None
    feed_ttl_sec: float = FEED_TTL_SEC

    def __init__(self, *, answerer: ScreeningResolver | None = None, http_client: httpx.AsyncClient | None = None,
                 receipts_root: Path | None = None, settle_ms: int = 1500, confirm_timeout_s: float = 15.0,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.http_client = http_client
        self.clock = clock or (lambda: datetime.now(UTC))
        self.jobs: OrderedDict[str, FeedJob] = OrderedDict()
        self.applier = HostedAtsApplier(HostedFormFiller(answerer=answerer), settle_ms=settle_ms,
                                        confirm_timeout_s=confirm_timeout_s, receipts_root=receipts_root)
        self._feed_cache: dict[str, tuple[float, Any]] = {}
        self.portal_wall: tuple[str, float] | None = None  # ("login"|"challenge", monotonic time)

    @property
    def answerer(self) -> ScreeningResolver | None:
        return self.applier.filler.answerer

    @answerer.setter
    def answerer(self, value: ScreeningResolver | None) -> None:
        self.applier.filler.answerer = value

    def configure(self, profile: dict[str, Any]) -> None:
        """Per-cycle hook (owner preferences, e.g. board lists). Default: nothing."""

    # --- HTTP ---------------------------------------------------------------------------
    def client(self) -> httpx.AsyncClient:
        return self.http_client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                                     headers={"user-agent": USER_AGENT})

    def memo_client(self) -> httpx.AsyncClient:
        """Injected client (tests) or a fresh client whose GETs are memoized for one board read."""
        return self.http_client or httpx.AsyncClient(transport=MemoTransport(), timeout=20, follow_redirects=False,
                                                     trust_env=False, headers={"user-agent": USER_AGENT})

    async def get_cached(self, key: str, loader: Callable[[], Any]) -> Any:
        """Feed reads are cached for 30 minutes (free public APIs: be a polite client)."""
        hit = self._feed_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < self.feed_ttl_sec:
            return hit[1]
        value = await loader()
        self._feed_cache[key] = (time.monotonic(), value)
        return value

    # --- discovery ----------------------------------------------------------------------
    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        raise NotImplementedError

    def remember(self, job: FeedJob) -> None:
        self.jobs[job.external_job_id] = job
        self.jobs.move_to_end(job.external_job_id)
        while len(self.jobs) > CACHE_LIMIT:
            self.jobs.popitem(last=False)

    def listing(self, job: FeedJob) -> JobListing:
        age = age_days_from(job.posted_at, self.clock())
        return JobListing(platform=self.platform, external_job_id=job.external_job_id, url=job.url, title=job.title,
                          company=job.company, posted_text=job.posted_at.isoformat() if job.posted_at else None,
                          posted_age_days=age, applicants=UNKNOWN_APPLICANTS)

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        output = []
        for job in await self.fetch(query, max(limit * 5, 50)):
            if not role_query_match(job.title, query):
                continue
            age = age_days_from(job.posted_at, self.clock())
            if job_age_days is not None and age is not None and age > job_age_days:
                continue
            self.remember(job)
            output.append(self.listing(job))
            if len(output) >= limit:
                break
        return output

    async def lookup(self, listing: JobListing) -> FeedJob | None:
        """Backlog jobs after a restart: re-read the (cached) feed and find the posting."""
        if listing.external_job_id in self.jobs:
            return self.jobs[listing.external_job_id]
        for job in await self.fetch(listing.title or "", 200):
            self.remember(job)
        return self.jobs.get(listing.external_job_id)

    # --- session / inspection -------------------------------------------------------------
    def active_wall(self) -> str | None:
        if self.portal_wall and time.monotonic() - self.portal_wall[1] < PORTAL_WALL_TTL_SEC:
            return self.portal_wall[0]
        return None

    async def check_session(self, page: Any) -> SessionCheck:
        wall = self.active_wall()
        if wall is not None:  # isolate only this portal: one AUTH HITL, jobs stay in the backlog
            return SessionCheck(AuthStatus.AUTH_REQUIRED, reason=wall,
                                details={"wall": wall, "retry_after_sec": PORTAL_WALL_TTL_SEC})
        return SessionCheck(AuthStatus.OK, details={"login": "not_required_public_feed"})

    async def resolve_apply_url(self, page: Any, job: FeedJob) -> str | None:
        return job.apply_url

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        job = await self.lookup(listing)
        if job is None:
            return JobDetail(listing=listing, applicants=UNKNOWN_APPLICANTS, posted_age_days=listing.posted_age_days,
                             already_applied=False, apply_mode="none", description=None)
        if self.active_wall() is not None:
            raise PortalWallActive(self.platform)
        try:
            apply_url = await self.resolve_apply_url(page, job)
        except (ApplyLinkChallenge, ApplyLinkLoginWall) as exc:
            # Fail closed: one HITL for this job (CAPTCHA / AUTH: the owner clears it in plain Brave),
            # then the whole portal reports AUTH_REQUIRED for 30 min - never a terminal FILTERED_OUT.
            wall = "login" if isinstance(exc, ApplyLinkLoginWall) else "challenge"
            self.portal_wall = (wall, time.monotonic())
            merged = replace(self.listing(job), url=listing.url or job.url)
            return JobDetail(listing=merged, applicants=UNKNOWN_APPLICANTS, posted_age_days=merged.posted_age_days,
                             already_applied=False, apply_mode="direct", challenge=wall,
                             description=job.description, salary_text=job.salary_text, location=job.location,
                             work_mode=job.work_mode, apply_url=job.apply_url, ats=None)
        self.portal_wall = None
        ats = classify_ats(apply_url)
        mode = "direct" if ats in SUPPORTED_ATS else ("external" if apply_url else "none")
        challenge = None
        if ats in SUPPORTED_ATS and apply_url:
            await self.applier.open_form(page, apply_url, ats)
            state = await form_state(page, None)
            challenge = "challenge" if state.get("challenge") else None
        merged = replace(self.listing(job), url=listing.url or job.url)
        return JobDetail(listing=merged, applicants=UNKNOWN_APPLICANTS, posted_age_days=merged.posted_age_days,
                         already_applied=False, apply_mode=mode, challenge=challenge, description=job.description,
                         salary_text=job.salary_text, location=job.location, work_mode=job.work_mode,
                         apply_url=apply_url, ats=ats)

    async def extract_form(self, page: Any) -> dict[str, Any]:
        return await extract_form(page)

    async def detect_portal_limit(self, page: Any) -> str | None:
        return None  # public boards and hosted ATS forms have no per-candidate daily cap

    # --- apply ------------------------------------------------------------------------------
    async def apply_job(self, page: Any, detail: JobDetail, profile: CandidateFacts | Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        guard_apply(existing_state)
        facts = profile if isinstance(profile, CandidateFacts) else CandidateFacts.from_profile(profile)
        if detail.challenge == "login":
            return ApplyResult(S.WAITING_FOR_USER, "portal_login_required", dry_run, question=HitlQuestion(
                kind="AUTH", prompt=f"[{self.platform}] sign in once in plain Brave (login-setup) to reveal "
                                    f"apply links: {detail.listing.url}", context={"platform": self.platform}))
        if detail.challenge:
            return ApplyResult(S.WAITING_FOR_USER, "ats_captcha_before_submit", dry_run,
                               question=HitlQuestion(kind="CAPTCHA", prompt=f"CAPTCHA on {detail.apply_url}",
                                                     context={"platform": self.platform}))
        if detail.apply_mode == "external":
            host = urlsplit(detail.apply_url or "").hostname or "unknown"
            return ApplyResult(S.FILTERED_OUT, f"external_unsupported_ats:{host}", dry_run)
        if detail.apply_mode != "direct" or detail.ats not in SUPPORTED_ATS:
            return ApplyResult(S.FILTERED_OUT if detail.apply_mode == "none" else S.FAILED,
                               f"apply_control_{detail.apply_mode}", dry_run)
        on_form = bool(detail.apply_url) and str(getattr(page, "url", "")).rstrip("/") == ats_form_url(
            detail.apply_url or "", detail.ats or "").rstrip("/")
        result = await self.applier.apply(page, detail, facts, platform=self.platform, dry_run=dry_run,
                                          hitl_answers=hitl_answers, navigate=not on_form)
        if self.attribution and result.receipt is not None:
            result = replace(result, receipt=result.receipt | {"attribution": self.attribution})
        return result
