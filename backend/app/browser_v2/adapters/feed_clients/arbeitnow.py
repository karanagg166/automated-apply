"""Arbeitnow public job-board API (one fixed host, integer pages only)."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.adapters.feed_clients.base import (
    FeedSource,
    FeedSourceError,
    check_page,
)
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import (
    employment,
    parse_date,
)
from backend.app.browser_v2.adapters.feed_clients.validation import posting

FEED_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowClient(FeedSource):
    source_name = "arbeitnow"

    def parse(self, item: Any, page: int) -> RawPosting:
        remote = "remote" if item.get("remote") is True else "unknown"
        return posting(
            source_name=self.source_name,
            source_job_id=item["slug"],
            original_url=item["url"],
            company_name=item.get("company_name"),
            title=item["title"],
            description=item.get("description"),
            location=item.get("location"),
            remote_type=remote,
            employment_type=employment(" ".join(item.get("job_types") or [])),
            # Feed tags include categories and seniority, not required skills.
            date_posted=parse_date(item.get("created_at")),
            source_verification_status="source_reported",
            data_provenance={
                "adapter": "ArbeitnowAdapter",
                "page": page,
                "attribution": "Arbeitnow",
                "attribution_url": "https://www.arbeitnow.com",
                "source_fields": {k: v for k, v in item.items() if k != "description"},
            },
        )

    async def fetch_jobs(self, page: int = 1, limit: int = 20) -> list[RawPosting]:
        check_page(limit, page)
        data = await self.request(FEED_URL, {"page": page})
        links = data.get("links") or {}
        if not isinstance(links, dict):
            raise FeedSourceError("Invalid pagination metadata")
        # Ignore upstream links; only fixed host + integer page is requested.
        self.next_cursor = str(page + 1) if links.get("next") and page < 100 else None
        return self.parse_records(data["data"], lambda item: self.parse(item, page), limit)
