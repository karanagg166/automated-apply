"""Greenhouse direct-ATS adapter (zero login).

Discovery uses the v2 `feed_clients.greenhouse.GreenhouseClient` (public
boards-api.greenhouse.io, fixed host, size-capped JSON) per configured board token:
`candidate_profiles.preferences.greenhouse_boards` ({token: company} or [token]) plus
the GREENHOUSE_BOARDS setting. The hosted form on boards/job-boards.greenhouse.io is
filled by the shared `HostedAtsApplier` (dry-run stops before Submit).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit

from backend.app.browser_v2.adapters.common import classify_ats, html_to_text
from backend.app.browser_v2.adapters.feed_clients.greenhouse import GreenhouseClient
from backend.app.browser_v2.adapters.feeds import FeedAdapter, FeedJob, fetch_all_pages

TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
MAX_BOARDS = 25
EMBED_FORM = "https://job-boards.greenhouse.io/embed/job_app?for={token}&token={job_id}"


def hosted_apply_url(token: str, job_id: str, absolute_url: str | None) -> str:
    """The Greenhouse-hosted form for a posting.

    Live 2026-11-26: boards with their own career site (stripe -> stripe.com/jobs/search?gh_jid=)
    report that as `absolute_url`, and job-boards.greenhouse.io/<token>/jobs/<id> 302s there too;
    the embed form always renders on greenhouse.io, so it is used whenever `absolute_url` is not
    already a hosted Greenhouse URL.
    """
    if classify_ats(absolute_url) == "greenhouse":
        return str(absolute_url)
    return EMBED_FORM.format(token=quote(token, safe=""), job_id=quote(str(job_id), safe=""))


def board_map(value: Any) -> dict[str, str | None]:
    """{token: company|None} from a dict or a list of tokens; invalid tokens are dropped."""
    if isinstance(value, dict):
        items = [(str(k), v if isinstance(v, str) else None) for k, v in value.items()]
    elif isinstance(value, (list, tuple)):
        items = [(str(v), None) for v in value if isinstance(v, str)]
    else:
        return {}
    return {token.strip(): company for token, company in items if TOKEN.match(token.strip())}


def board_from_url(url: str | None) -> str | None:
    parts = urlsplit(url or "")
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) >= 3 and segments[1] == "jobs" and TOKEN.match(segments[0]):
        return segments[0]
    return None


class GreenhouseAdapter(FeedAdapter):
    platform = "greenhouse"

    def __init__(self, *, boards: dict[str, str | None] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.static_boards = dict(boards or {})
        self.boards: dict[str, str | None] = dict(self.static_boards)

    def configure(self, profile: dict[str, Any]) -> None:
        prefs = profile.get("preferences") or {}
        boards = dict(self.static_boards)
        try:
            from backend.app.core.config import get_settings

            boards |= board_map(get_settings().GREENHOUSE_BOARDS)
        except Exception:  # noqa: BLE001, S110 - settings are optional for the v2 worker
            pass
        boards |= board_map(prefs.get("greenhouse_boards"))
        self.boards = dict(list(boards.items())[:MAX_BOARDS])

    async def fetch_board(self, token: str, company: str | None) -> list[FeedJob]:
        async def load() -> list[FeedJob]:
            client = self.memo_client()
            try:
                source = GreenhouseClient(client, board_token=token, company_name=company)
                jobs = await fetch_all_pages(
                    source, lambda limit, page: source.fetch_jobs(board_token=token, limit=limit, page=page))
            finally:
                if self.http_client is None:
                    await client.aclose()
            return [FeedJob(external_job_id=str(job.source_job_id), url=job.original_url, title=job.title,
                            company=job.company_name or company or token,
                            apply_url=hosted_apply_url(token, str(job.source_job_id),
                                                       job.application_url or job.original_url),
                            description=html_to_text(job.description),
                            posted_at=job.date_posted, location=job.location,
                            work_mode=None if job.remote_type == "unknown" else job.remote_type)
                    for job in jobs if job.source_job_id]

        return list(await self.get_cached(f"greenhouse:{token}", load))

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        jobs: list[FeedJob] = []
        for token, company in self.boards.items():
            try:
                jobs.extend(await self.fetch_board(token, company))
            except Exception:  # noqa: BLE001, S112 - one broken/renamed board must not stop the others
                continue
            # Never stop after the first big board (live: stripe's 772 jobs starved gitlab);
            # every board is read (30-min cache) and query/age filters run afterwards.
        return jobs

    async def lookup(self, listing: Any) -> FeedJob | None:
        if listing.external_job_id in self.jobs:
            return self.jobs[listing.external_job_id]
        token = board_from_url(listing.url)
        if token and token not in self.boards:
            self.boards[token] = listing.company
        return await super().lookup(listing)
