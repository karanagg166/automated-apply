"""Lever direct-ATS adapter (zero login).

Discovery uses the v2 `feed_clients.lever.LeverClient` (api.lever.co /
api.eu.lever.co postings feed, allowlisted per board, identity-checked hosted URLs)
for `preferences.lever_boards` + the LEVER_BOARDS setting. The hosted form at
jobs.lever.co/<board>/<id>/apply is filled by `HostedAtsApplier`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.common import html_to_text
from backend.app.browser_v2.adapters.feed_clients.lever import LeverClient
from backend.app.browser_v2.adapters.feeds import FeedAdapter, FeedJob, fetch_all_pages
from backend.app.browser_v2.adapters.greenhouse import MAX_BOARDS, board_map
from backend.app.browser_v2.adapters.watchlist import active_boards


def board_from_url(url: str | None) -> str | None:
    parts = urlsplit(url or "")
    segments = [s for s in parts.path.split("/") if s]
    return segments[0] if parts.hostname in {"jobs.lever.co", "jobs.eu.lever.co"} and len(segments) >= 2 else None


def created_at(fields: dict[str, Any]) -> datetime | None:
    value = fields.get("createdAt")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return None


class LeverAdapter(FeedAdapter):
    platform = "lever"

    def __init__(self, *, boards: dict[str, str | None] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.static_boards = dict(boards or {})
        self.boards: dict[str, str | None] = dict(self.static_boards)

    def configure(self, profile: dict[str, Any]) -> None:
        prefs = profile.get("preferences") or {}
        boards = dict(self.static_boards)
        try:
            from backend.app.core.config import get_settings

            boards |= board_map(get_settings().LEVER_BOARDS)
        except Exception:  # noqa: BLE001, S110
            pass
        boards |= board_map(prefs.get("lever_boards"))
        boards = active_boards("lever", boards, prefs)  # Milestone 2: owner-paused boards are skipped
        self.boards = dict(list(boards.items())[:MAX_BOARDS])

    async def fetch_board(self, board: str, company: str | None) -> list[FeedJob]:
        async def load() -> list[FeedJob]:
            client = self.memo_client()
            try:
                source = LeverClient(client)
                source.boards = {board: company or board}
                jobs = await fetch_all_pages(source, lambda limit, page: source.fetch_jobs(limit=limit, page=page))
            finally:
                if self.http_client is None:
                    await client.aclose()
            return [FeedJob(external_job_id=str(job.source_job_id), url=job.original_url, title=job.title,
                            company=job.company_name or company or board,
                            apply_url=job.application_url or job.original_url,
                            description=html_to_text(job.description),
                            posted_at=created_at(dict(job.source_fields or {})),
                            location=job.location, salary_text=job.salary_raw,
                            work_mode=None if job.remote_type == "unknown" else job.remote_type)
                    for job in jobs if job.source_job_id]

        return list(await self.get_cached(f"lever:{board}", load))

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        jobs: list[FeedJob] = []
        for board, company in self.boards.items():
            try:
                jobs.extend(await self.fetch_board(board, company))
            except Exception:  # noqa: BLE001, S112 - one broken board must not stop the others
                continue
            # Read every board (30-min cache); never let the first big board starve the rest.
        return jobs

    async def lookup(self, listing: Any) -> FeedJob | None:
        if listing.external_job_id in self.jobs:
            return self.jobs[listing.external_job_id]
        board = board_from_url(listing.url)
        if board and board not in self.boards:
            self.boards[board] = listing.company
        return await super().lookup(listing)
