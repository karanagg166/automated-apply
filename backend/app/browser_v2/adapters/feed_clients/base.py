"""Shared request/record plumbing for the v2 fixed-host feed clients (port of v1 `DirectAdapter`).

Same contract as v1: GET only, no redirects, 15 s per request, 8 MiB decoded-body cap,
HTTP 200 + a JSON document of the expected top-level type, one retry (after 0.1 s) on a
5xx or transport error except where the provider asks for single attempts (Remotive).
A record that fails validation is dropped (counted in `record_errors`); a request or
schema failure raises, so the caller isolates the whole board/feed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feed_clients.http import (
    ConditionalHttp,
    HttpStatusError,
    RateLimited,
)
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting

MAX_RESPONSE_BYTES = 32 * 1024 * 1024  # Greenhouse boards with content=true reach 10-20 MiB (Anthropic, Databricks)
REQUEST_TIMEOUT_SEC = 15.0
RETRY_PAUSE_SEC = 0.1
RECORD_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError, KeyError, AttributeError, OverflowError)


class FeedSourceError(RuntimeError):
    """The provider response (or the request itself) is unusable; never a per-record error."""


def check_page(limit: int, page: int) -> None:
    """v1 bounds (DiscoveryQuery): 1 <= limit <= 100, 1 <= page <= 100."""
    if not (1 <= limit <= 100 and 1 <= page <= 100):
        raise ValueError("page/limit out of range")


class FeedSource:
    source_name = ""
    attempts = 2  # one retry on 5xx / transport errors
    JSON_TYPES: tuple[type, ...] = (dict,)

    def __init__(self, http_client: httpx.AsyncClient, *, http: ConditionalHttp | None = None) -> None:
        # Discovery keeps v1 pacing (none): the per-host spacing is for the Phase 9B watchers.
        self.http = http or ConditionalHttp(http_client, min_interval=0.0)
        self.next_cursor: str | None = None
        self.record_errors: list[str] = []

    def allowed(self, url: str) -> bool:
        """Defense in depth: subclasses restrict the URLs they will GET."""
        return True

    async def request(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        if not self.allowed(url):
            raise FeedSourceError("feed URL is not allowlisted")
        for attempt in range(self.attempts):
            retry = attempt + 1 < self.attempts
            try:
                result = await self.http.get(url, params=params, max_bytes=MAX_RESPONSE_BYTES,
                                             timeout=REQUEST_TIMEOUT_SEC)
            except RateLimited as exc:
                if exc.status >= 500 and retry:
                    await asyncio.sleep(RETRY_PAUSE_SEC)
                    continue
                raise
            except HttpStatusError as exc:
                if exc.status >= 500 and retry:
                    await asyncio.sleep(RETRY_PAUSE_SEC)
                    continue
                raise
            except httpx.TransportError:
                if retry:
                    await asyncio.sleep(RETRY_PAUSE_SEC)
                    continue
                raise FeedSourceError("provider transport failed") from None
            if result.status != 200 or result.body is None:
                raise HttpStatusError(result.status)
            try:
                data = json.loads(result.body)
            except (ValueError, UnicodeError):
                raise FeedSourceError("provider returned invalid JSON") from None
            if not isinstance(data, self.JSON_TYPES):
                raise FeedSourceError("provider returned an invalid top-level schema")
            return data
        raise FeedSourceError("provider unavailable")  # pragma: no cover - the loop always returns/raises

    def parse_records(self, records: Any, parser: Callable[[Any], RawPosting], limit: int) -> list[RawPosting]:
        if not isinstance(records, list):
            raise FeedSourceError("provider returned an invalid record collection")
        result = []
        self.record_errors = []
        for index, record in enumerate(records[:limit]):
            try:
                result.append(parser(record))
            except RECORD_ERRORS:
                self.record_errors.append(f"Record {index}: invalid or missing listing evidence")
        return result
