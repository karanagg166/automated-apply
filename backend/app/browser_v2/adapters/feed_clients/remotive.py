"""Remotive public remote-jobs API (one fixed host; Remotive asks for <= 4 reads a day)."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.adapters.feed_clients.base import FeedSource, check_page
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import (
    employment,
    parse_date,
    salary_fields,
)
from backend.app.browser_v2.adapters.feed_clients.validation import posting

FEED_URL = "https://remotive.com/api/remote-jobs"
MAX_FEED_RECORDS = 1000


class RemotiveClient(FeedSource):
    source_name = "remotive"
    attempts = 1  # never re-request a rate-limited free feed

    def parse(self, item: Any) -> RawPosting:
        raw = item.get("salary") or None
        source_id = item.get("id")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, (str, int))
            or not str(source_id).strip()
        ):
            raise ValueError("Remotive record requires a non-empty scalar id")
        return posting(
            source_name=self.source_name,
            source_job_id=str(source_id),
            original_url=item["url"],
            company_name=item.get("company_name"),
            title=item["title"],
            description=item.get("description"),
            location=item.get("candidate_required_location"),
            remote_type="remote",
            employment_type=employment(item.get("job_type")),
            salary_raw=raw,
            **salary_fields(raw),
            skills_required=item.get("tags") or [],
            date_posted=parse_date(item.get("publication_date")),
            source_verification_status="source_reported",
            data_provenance={"adapter": "RemotiveAdapter", "attribution": "Remotive", "feed_delay_hours": 24},
        )

    async def fetch_jobs(self, category: str = "software-dev", limit: int = 20, page: int = 1,
                         search_query: str = "") -> list[RawPosting]:
        """Remotive paginates locally over one download of the first `page * limit` records."""
        check_page(limit, page)
        if page * limit > MAX_FEED_RECORDS:
            raise ValueError("Remotive local pagination is capped at 1000 feed records")
        data = await self.request(FEED_URL, {"category": category, "limit": min(page * limit, MAX_FEED_RECORDS),
                                             "search": search_query})
        return self.parse_records(data["jobs"][(page - 1) * limit : page * limit], self.parse, limit)
