"""Credential-free ATS GET feeds scoped to allowlisted boards (port of v1 `PublicATSAdapter`)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feed_clients.base import (
    RECORD_ERRORS,
    FeedSource,
    FeedSourceError,
    check_page,
)
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import hosted_job_url


class AtsBoardSource(FeedSource):
    """`boards` ({board: employer}) is the allowlist; no request-supplied board or URL is fetched."""

    job_host = ""

    def __init__(self, http_client: httpx.AsyncClient, *, boards: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(http_client, **kwargs)
        self.boards: dict[str, str] = dict(boards or {})

    def feed_url(self, board: str) -> str:
        raise NotImplementedError

    def feed_params(self) -> dict[str, str]:
        raise NotImplementedError

    def records(self, data: Any) -> Any:
        raise NotImplementedError

    def visible(self, records: list[Any]) -> list[Any]:
        return records

    def parse(self, item: Any, board: str, company: str) -> RawPosting:
        raise NotImplementedError

    def allowed(self, url: str) -> bool:
        return url in {self.feed_url(board) for board in self.boards}

    def job_url(self, value: Any, board: str, *, application: bool = False) -> str:
        return hosted_job_url(value, board, self.source_name, self.job_host, application=application)

    async def fetch_jobs(self, limit: int = 20, page: int = 1) -> list[RawPosting]:
        check_page(limit, page)
        if not self.boards:
            raise FeedSourceError(f"no {self.source_name} boards configured")
        start, remaining = (page - 1) * limit, limit
        jobs: list[RawPosting] = []
        errors: list[str] = []
        seen: dict[tuple[str, str | None], str] = {}
        self.next_cursor = None
        for board_index, (board, company) in enumerate(self.boards.items()):
            data = await self.request(self.feed_url(board), self.feed_params())
            records = self.records(data)
            if not isinstance(records, list):
                raise FeedSourceError("Invalid ATS jobs collection")
            records = self.visible(records)
            if start >= len(records):
                start -= len(records)
                continue
            selected = records[start : start + remaining]
            for index, record in enumerate(selected):
                try:
                    job = self.parse(record, board, company)
                    key = (board, job.source_job_id)
                    evidence = json.dumps(record, sort_keys=True)
                    if key in seen:
                        if seen[key] != evidence:
                            raise ValueError("Inconsistent duplicate posting")
                        continue
                    seen[key] = evidence
                    jobs.append(job)
                except RECORD_ERRORS:
                    errors.append(f"Board {board_index}, record {index}: invalid or inconsistent listing evidence")
            remaining -= len(selected)
            if len(records) > start + len(selected) or board_index < len(self.boards) - 1:
                self.next_cursor = str(page + 1) if page < 100 else None
            start = 0
            if remaining <= 0:
                break
        self.record_errors = errors
        return jobs
