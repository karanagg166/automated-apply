"""Five more zero-cost discovery sources for the v2 worker (AGENTS.md §4.2 Tiers 2-3).

Each wraps the reviewed, read-only v1 client in `services.job_sources` (fixed hosts,
size-capped JSON, allowlisted boards) as a v2 `FeedAdapter`, so discovery, dedup,
filters, the semantic-cache/LLM resolver, Telegram HITL and the never-replay state
machine are shared with every other portal:

| platform | source | apply path |
|---|---|---|
| remotive | remotive.com/api/remote-jobs (<= 4 fetches/day, persisted) | employer link read from the listing page -> Greenhouse/Lever handoff or external |
| arbeitnow | arbeitnow.com/api/job-board-api | employer link read from the listing page |
| hacker_news | hn.algolia.com "Who is hiring" | first employer link in the comment |
| ashby | api.ashbyhq.com (allowlisted boards) | hosted Ashby form -> manual handoff (`external_unsupported_ats`) |
| smartrecruiters | api.smartrecruiters.com (allowlisted boards) | hosted SmartRecruiters form -> manual handoff |

Greenhouse/Lever links found behind any of them are handed to those adapters by the
service (`ats_handoff:<ats>:<id>`); everything else terminates cleanly. No login, no
browser for discovery; at most one listing-page navigation per inspected job.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.common import html_to_text
from backend.app.browser_v2.adapters.feeds import (
    FeedAdapter,
    FeedJob,
    external_apply_link,
    fetch_all_pages,
)
from backend.app.browser_v2.adapters.greenhouse import MAX_BOARDS, board_map

DAY_SEC = 24 * 3600
REMOTIVE_MAX_FETCHES_PER_DAY = 4
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
BARE_URL = re.compile(r"https://[^\s<>\"')]+")
EMPLOYER_HINT = re.compile(r"greenhouse|lever\.co|ashbyhq|smartrecruiters|workable|careers?|jobs?|apply", re.IGNORECASE)


def to_feed_job(job: Any, company: str | None = None, *, apply_url: str | None = None) -> FeedJob:
    """v1 NormalizedJob -> FeedJob (plain-text JD, https apply link only)."""
    link = apply_url if apply_url is not None else (job.application_url or None)
    return FeedJob(external_job_id=str(job.source_job_id), url=job.original_url, title=job.title,
                   company=job.company_name or company, apply_url=link if link and link.startswith("https://")
                   else None, description=html_to_text(job.description), posted_at=job.date_posted,
                   location=job.location, salary_text=job.salary_raw,
                   work_mode=None if job.remote_type == "unknown" else job.remote_type)


def employer_link(raw_html: str | None, *, exclude_hosts: frozenset[str]) -> str | None:
    """First off-site https link in an HN comment, preferring ATS/careers URLs."""
    text = html_lib.unescape(raw_html or "")
    links = [html_lib.unescape(m) for m in HREF.findall(text)] + BARE_URL.findall(text)
    candidates = []
    for link in links:
        link = link.rstrip(".,;")
        host = (urlsplit(link).hostname or "").lower()
        if link.startswith("https://") and host and host not in exclude_hosts:
            candidates.append(link)
    preferred = [c for c in candidates if EMPLOYER_HINT.search(c)]
    return (preferred or candidates or [None])[0]


class FetchBudget:
    """Persisted per-source fetch cap (survives worker restarts): Remotive asks for <= 4/day."""

    def __init__(self, name: str, max_per_day: int, path: Path | None = None) -> None:
        self.name = name
        self.max_per_day = max_per_day
        self._path = path

    @property
    def path(self) -> Path:
        if self._path is None:
            from backend.app.browser_v2 import profile as brave_profile

            self._path = brave_profile.runtime_dir() / "feed-budget.json"
        return self._path

    def _load(self) -> dict[str, list[float]]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def recent(self, now: float | None = None) -> list[float]:
        now = time.time() if now is None else now
        return [t for t in self._load().get(self.name, []) if isinstance(t, (int, float)) and now - t < DAY_SEC]

    def allow(self, now: float | None = None) -> bool:
        return len(self.recent(now)) < self.max_per_day

    def record(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        data = self._load()
        data[self.name] = [*self.recent(now), now]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.write_text(json.dumps(data))
        except OSError:  # an unwritable stamp file must not stop discovery; the TTL still applies
            pass


class SourceFeedAdapter(FeedAdapter):
    """Shared plumbing: one cached read per TTL, optional listing-page apply-link resolution."""

    cache_key = "source"
    feed_ttl_sec: float = 60 * 60
    origin_hosts: frozenset[str] = frozenset()

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        raise NotImplementedError

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        async def load() -> list[FeedJob]:
            client = self.memo_client()
            try:
                return await self.load_jobs(client)
            finally:
                if self.http_client is None:
                    await client.aclose()

        return list(await self.get_cached(self.cache_key, load))

    async def resolve_apply_url(self, page: Any, job: FeedJob) -> str | None:
        if job.apply_url and (urlsplit(job.apply_url).hostname or "") not in self.origin_hosts:
            return job.apply_url
        if self.origin_hosts and page is not None:
            return await external_apply_link(page, job.url, self.origin_hosts, settle_ms=self.applier.settle_ms)
        return job.apply_url


class RemotiveAdapter(SourceFeedAdapter):
    platform = "remotive"
    attribution = "Listing via Remotive (remotive.com)"
    cache_key = "remotive:software-dev"
    feed_ttl_sec = DAY_SEC / REMOTIVE_MAX_FETCHES_PER_DAY  # 6 h
    origin_hosts = frozenset({"remotive.com", "www.remotive.com"})

    def __init__(self, *, budget: FetchBudget | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.budget = budget or FetchBudget("remotive", REMOTIVE_MAX_FETCHES_PER_DAY)

    async def get_cached(self, key: str, loader: Any) -> Any:
        hit = self._feed_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < self.feed_ttl_sec:
            return hit[1]
        if not self.budget.allow():
            return hit[1] if hit is not None else []  # daily cap reached: stale cache or nothing
        self.budget.record()
        value = await loader()
        self._feed_cache[key] = (time.monotonic(), value)
        return value

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        from backend.app.services.job_sources.direct_api import (
            RemotiveAdapter as Source,
        )

        source = Source(http_client=client)
        # One request per read (Remotive paginates locally over the same download).
        jobs = await source.fetch_jobs(category="software-dev", limit=100, page=1)
        return [to_feed_job(job, apply_url=None) for job in jobs if job.source_job_id]


class ArbeitnowAdapter(SourceFeedAdapter):
    platform = "arbeitnow"
    attribution = "Listing via Arbeitnow (arbeitnow.com)"
    cache_key = "arbeitnow:board"
    origin_hosts = frozenset({"arbeitnow.com", "www.arbeitnow.com"})

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        from backend.app.services.job_sources.direct_api import (
            ArbeitnowAdapter as Source,
        )

        source = Source(http_client=client)
        jobs = await fetch_all_pages(source, lambda limit, page: source.fetch_jobs(page=page, limit=limit),
                                     max_pages=3)
        return [to_feed_job(job, apply_url=None) for job in jobs if job.source_job_id]


class HackerNewsAdapter(SourceFeedAdapter):
    platform = "hacker_news"
    attribution = "Listing via Hacker News 'Who is hiring?'"
    cache_key = "hn:whoishiring"
    feed_ttl_sec = 3 * 60 * 60

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        from backend.app.services.job_sources.direct_api import (
            HackerNewsHiringAdapter as Source,
        )

        raw: dict[str, str] = {}

        class Capturing(Source):
            """The v1 client keeps only tag-stripped text: keep each comment's HTML for its hrefs."""

            async def request(self, client: Any, url: Any, params: Any = None) -> Any:
                data = await super().request(client, url, params)
                for hit in (data or {}).get("hits", []) if isinstance(data, dict) else []:
                    if isinstance(hit, dict) and hit.get("comment_text"):
                        raw[str(hit.get("objectID"))] = str(hit["comment_text"])
                return data

        source = Capturing(http_client=client)
        jobs = await fetch_all_pages(source, lambda limit, page: source.fetch_jobs(limit=limit, page=page),
                                     max_pages=3)
        exclude = frozenset({"news.ycombinator.com", "hn.algolia.com"})
        return [to_feed_job(job, apply_url=employer_link(raw.get(str(job.source_job_id)) or job.description,
                                                         exclude_hosts=exclude) or "")
                for job in jobs if job.source_job_id]


class _BoardSource(SourceFeedAdapter):
    """Allowlisted ATS boards: `preferences.<name>_boards` + the <NAME>_BOARDS setting."""

    setting = ""
    preference = ""

    def __init__(self, *, boards: dict[str, str | None] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.static_boards = dict(boards or {})
        self.boards: dict[str, str | None] = dict(self.static_boards)

    def configure(self, profile: dict[str, Any]) -> None:
        prefs = profile.get("preferences") or {}
        boards = dict(self.static_boards)
        try:
            from backend.app.core.config import get_settings

            boards |= board_map(getattr(get_settings(), self.setting))
        except Exception:  # noqa: BLE001, S110 - settings are optional for the v2 worker
            pass
        boards |= board_map(prefs.get(self.preference))
        self.boards = dict(list(boards.items())[:MAX_BOARDS])

    def source(self, client: Any) -> Any:
        raise NotImplementedError

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        jobs: list[FeedJob] = []
        for board, company in self.boards.items():
            async def load(board: str = board, company: str | None = company) -> list[FeedJob]:
                client = self.memo_client()
                try:
                    source = self.source(client)
                    source.boards = {board: company or board}
                    found = await fetch_all_pages(
                        source, lambda limit, page: source.fetch_jobs(limit=limit, page=page))
                finally:
                    if self.http_client is None:
                        await client.aclose()
                return [to_feed_job(job, company or board) for job in found if job.source_job_id]

            try:
                jobs.extend(await self.get_cached(f"{self.platform}:{board}", load))
            except Exception:  # noqa: BLE001, S112 - one broken/renamed board must not stop the others
                continue
        return jobs


class AshbyAdapter(_BoardSource):
    platform = "ashby"
    setting, preference = "ASHBY_BOARDS", "ashby_boards"

    def source(self, client: Any) -> Any:
        from backend.app.services.job_sources.public_ats import AshbyAdapter as Source

        return Source(http_client=client)


class SmartRecruitersAdapter(_BoardSource):
    platform = "smartrecruiters"
    setting, preference = "SMARTRECRUITERS_BOARDS", "smartrecruiters_boards"

    def source(self, client: Any) -> Any:
        from backend.app.services.job_sources.smartrecruiters import (
            SmartRecruitersAdapter as Source,
        )

        return Source(http_client=client)
