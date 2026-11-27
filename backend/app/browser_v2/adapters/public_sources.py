"""Five more zero-cost discovery sources for the v2 worker (AGENTS.md §4.2 Tiers 2-3).

Each wraps a read-only v2 client from `adapters.feed_clients` (fixed hosts,
size-capped JSON, allowlisted boards) as a v2 `FeedAdapter`, so discovery, dedup,
filters, the semantic-cache/LLM resolver, Telegram HITL and the never-replay state
machine are shared with every other portal:

| platform | source | apply path |
|---|---|---|
| remotive | remotive.com/api/remote-jobs (<= 4 fetches/day, persisted in watcher_state) | employer link read from the listing page -> Greenhouse/Lever handoff or external |
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
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.common import html_to_text
from backend.app.browser_v2.adapters.feed_clients.arbeitnow import ArbeitnowClient
from backend.app.browser_v2.adapters.feed_clients.ashby import AshbyClient
from backend.app.browser_v2.adapters.feed_clients.hacker_news import HackerNewsClient
from backend.app.browser_v2.adapters.feed_clients.remotive import RemotiveClient
from backend.app.browser_v2.adapters.feed_clients.smartrecruiters import (
    SmartRecruitersClient,
)
from backend.app.browser_v2.adapters.feeds import (
    FeedAdapter,
    FeedJob,
    external_apply_link,
    fetch_all_pages,
)
from backend.app.browser_v2.adapters.greenhouse import MAX_BOARDS, board_map
from backend.app.browser_v2.adapters.watchlist import active_boards
from backend.app.browser_v2.store.phase9_records import WatcherState

DAY_SEC = 24 * 3600
REMOTIVE_MAX_FETCHES_PER_DAY = 4
REMOTIVE_BUDGET_SOURCE = "remotive:budget"
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
BARE_URL = re.compile(r"https://[^\s<>\"')]+")
EMPLOYER_HINT = re.compile(r"greenhouse|lever\.co|ashbyhq|smartrecruiters|workable|careers?|jobs?|apply", re.IGNORECASE)


def to_feed_job(job: Any, company: str | None = None, *, apply_url: str | None = None) -> FeedJob:
    """RawPosting (or any object with its attributes) -> FeedJob (plain-text JD, https apply link only)."""
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
    """Per-source fetch cap: Remotive asks for <= 4/day.

    In memory by default (no local state files); an explicit `path` keeps the legacy JSON stamp
    file. The worker binds `StoreFetchBudget` (watcher_state) via `RemotiveAdapter.use_store`.
    """

    def __init__(self, name: str, max_per_day: int, path: Path | None = None) -> None:
        self.name = name
        self.max_per_day = max_per_day
        self._path = path
        self._stamps: list[float] = []

    @property
    def path(self) -> Path | None:
        return self._path

    def _load(self) -> dict[str, list[float]]:
        if self._path is None:
            return {self.name: list(self._stamps)}
        try:
            data = json.loads(self._path.read_text())
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
        stamps = [*self.recent(now), now]
        if self._path is None:
            self._stamps = stamps
            return
        data = self._load()
        data[self.name] = stamps
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._path.write_text(json.dumps(data))
        except OSError:  # an unwritable stamp file must not stop discovery; the TTL still applies
            pass


class StoreFetchBudget:
    """Fetch cap persisted in `watcher_state` (row `source`, e.g. "remotive:budget").

    `budget_day`/`budget_used` count the current UTC day; an hour window also stamps the bucket
    start in `last_poll_at` of that dedicated row. Shared by the adapter and the Phase 9B watcher.
    """

    def __init__(self, store: Any, source: str, limit: int, *, window: str = "day",
                 clock: Callable[[], datetime] | None = None) -> None:
        if window not in ("day", "hour"):
            raise ValueError("window must be day or hour")
        self.store = store
        self.source = source
        self.limit = limit
        self.window = window
        self.clock = clock or (lambda: datetime.now(UTC))

    def bucket(self, now: datetime) -> datetime:
        now = now.astimezone(UTC)
        start = now.replace(minute=0, second=0, microsecond=0)
        return start if self.window == "hour" else start.replace(hour=0)

    def used(self, state: WatcherState | None, bucket: datetime) -> int:
        if state is None or state.budget_day != bucket.date():
            return 0
        if self.window == "hour" and state.last_poll_at != bucket:
            return 0
        return state.budget_used

    async def remaining(self) -> int:
        bucket = self.bucket(self.clock())
        return max(0, self.limit - self.used(await self.store.get_watcher_state(self.source), bucket))

    async def acquire(self, count: int = 1) -> bool:
        bucket = self.bucket(self.clock())
        state = await self.store.get_watcher_state(self.source)
        used = self.used(state, bucket)
        if used + count > self.limit:
            return False
        base = state or WatcherState(source=self.source)
        await self.store.save_watcher_state(replace(
            base, budget_day=bucket.date(), budget_used=used + count,
            last_poll_at=bucket if self.window == "hour" else base.last_poll_at))
        return True


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

    def __init__(self, *, budget: FetchBudget | StoreFetchBudget | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.budget = budget or FetchBudget("remotive", REMOTIVE_MAX_FETCHES_PER_DAY)

    def use_store(self, store: Any) -> None:
        """Persist the daily cap in watcher_state (shared with the Phase 9B Remotive watcher)."""
        self.budget = StoreFetchBudget(store, REMOTIVE_BUDGET_SOURCE, REMOTIVE_MAX_FETCHES_PER_DAY, clock=self.clock)

    async def spend(self) -> bool:
        if isinstance(self.budget, StoreFetchBudget):
            return await self.budget.acquire()
        if not self.budget.allow():
            return False
        self.budget.record()
        return True

    async def get_cached(self, key: str, loader: Any) -> Any:
        hit = self._feed_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < self.feed_ttl_sec:
            return hit[1]
        if not await self.spend():
            return hit[1] if hit is not None else []  # daily cap reached: stale cache or nothing
        value = await loader()
        self._feed_cache[key] = (time.monotonic(), value)
        return value

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        source = RemotiveClient(client)
        # One request per read (Remotive paginates locally over the same download).
        jobs = await source.fetch_jobs(category="software-dev", limit=100, page=1)
        return [to_feed_job(job, apply_url=None) for job in jobs if job.source_job_id]


class ArbeitnowAdapter(SourceFeedAdapter):
    platform = "arbeitnow"
    attribution = "Listing via Arbeitnow (arbeitnow.com)"
    cache_key = "arbeitnow:board"
    origin_hosts = frozenset({"arbeitnow.com", "www.arbeitnow.com"})

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        source = ArbeitnowClient(client)
        jobs = await fetch_all_pages(source, lambda limit, page: source.fetch_jobs(page=page, limit=limit),
                                     max_pages=3)
        return [to_feed_job(job, apply_url=None) for job in jobs if job.source_job_id]


class HackerNewsAdapter(SourceFeedAdapter):
    platform = "hacker_news"
    attribution = "Listing via Hacker News 'Who is hiring?'"
    cache_key = "hn:whoishiring"
    feed_ttl_sec = 3 * 60 * 60

    async def load_jobs(self, client: Any) -> list[FeedJob]:
        source = HackerNewsClient(client)
        jobs = await fetch_all_pages(source, lambda limit, page: source.fetch_jobs(limit=limit, page=page),
                                     max_pages=3)
        raw = source.comment_html  # the posting keeps tag-stripped text: each comment's HTML has the hrefs
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
        boards = active_boards(self.preference.removesuffix("_boards"), boards, prefs)  # Milestone 2: paused
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
        return AshbyClient(client)


class SmartRecruitersAdapter(_BoardSource):
    platform = "smartrecruiters"
    setting, preference = "SMARTRECRUITERS_BOARDS", "smartrecruiters_boards"

    def source(self, client: Any) -> Any:
        return SmartRecruitersClient(client)
