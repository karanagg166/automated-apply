"""Greenhouse public job-board API (boards-api.greenhouse.io), one allowlisted board token."""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feed_clients.base import (
    FeedSource,
    FeedSourceError,
    check_page,
)
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import (
    parse_date,
    remote_policy,
)
from backend.app.browser_v2.adapters.feed_clients.validation import posting

BOARD_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,100}")


def feed_url(token: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseClient(FeedSource):
    source_name = "greenhouse"

    def __init__(self, http_client: httpx.AsyncClient, *, board_token: str, company_name: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(http_client, **kwargs)
        self.board_token = board_token
        self.company_name = company_name

    def parse(self, item: Any, token: str) -> RawPosting:
        location = (item.get("location") or {}).get("name")
        source_id = item.get("id")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, (str, int))
            or not str(source_id).strip()
        ):
            raise ValueError("Greenhouse record requires a non-empty scalar id")
        return posting(
            source_name=self.source_name,
            source_job_id=str(source_id),
            original_url=item["absolute_url"],
            application_url=item["absolute_url"],
            company_name=item.get("company_name") or self.company_name,
            title=item["title"],
            description=item.get("content"),
            location=location,
            remote_type=remote_policy(location),
            date_posted=parse_date(item.get("first_published")),
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": "GreenhouseAdapter",
                "board_token": token,
                "updated_at": item.get("updated_at"),
                "source_fields": {k: v for k, v in item.items() if k != "content"},
            },
        )

    async def fetch_jobs(self, board_token: str | None = None, limit: int = 20, page: int = 1) -> list[RawPosting]:
        """Slice `limit` postings of page `page` out of the (whole-board) response."""
        check_page(limit, page)
        token = board_token or self.board_token
        self.next_cursor = None
        if not BOARD_TOKEN.fullmatch(token):
            raise FeedSourceError("Invalid board token")
        data = await self.request(feed_url(token), {"content": "true"})
        records = data["jobs"]
        if not isinstance(records, list):
            raise FeedSourceError("Invalid board jobs collection")
        start = (page - 1) * limit
        if start >= len(records):
            return []
        selected = records[start : start + limit]
        jobs = self.parse_records(selected, lambda item: self.parse(item, token), limit)
        if len(records) > start + len(selected):
            self.next_cursor = str(page + 1)
        return jobs
