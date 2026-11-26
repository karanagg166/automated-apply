"""Conditional, size-capped, per-host-paced GETs over an injected `httpx.AsyncClient`.

No client is ever created here (the caller owns its lifetime) and nothing is persisted:
the Phase 9B watchers store the returned `Validators` themselves and pass them back on
the next poll. A 304, or an unchanged body hash when the server sends no validators,
is reported as `not_modified` so the caller can skip parsing entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feeds import USER_AGENT

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_MIN_INTERVAL_SEC = 1.0
RETRY_AFTER_CAP_SEC = 3600.0


@dataclass(frozen=True)
class Validators:
    """What a server told us about the last body: replayed as If-None-Match / If-Modified-Since."""

    etag: str | None = None
    last_modified: str | None = None
    body_hash: str | None = None  # sha256 hex of the last body (servers that send no validators)


@dataclass(frozen=True)
class FetchResult:
    status: int
    body: bytes | None  # None when not_modified
    validators: Validators
    not_modified: bool = False
    retry_after: float | None = None


class FeedHttpError(Exception):
    """Base class for ConditionalHttp failures."""


class HttpStatusError(FeedHttpError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


class RateLimited(HttpStatusError):
    """429 (or 503 with Retry-After): wait `retry_after` seconds (None when the server gave none)."""

    def __init__(self, retry_after: float | None, status: int = 429) -> None:
        super().__init__(status)
        self.retry_after = retry_after


class ResponseTooLarge(FeedHttpError):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"response exceeds {limit} bytes")


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Retry-After as delta-seconds or an HTTP-date, clamped to [0, 3600]; None when unusable."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - (now or datetime.now(UTC))).total_seconds()
    if math.isnan(seconds):
        return None
    return min(RETRY_AFTER_CAP_SEC, max(0.0, seconds))


class ConditionalHttp:
    """One request at a time per host, at least `min_interval` seconds apart (injectable clock/sleeper)."""

    def __init__(self, client: httpx.AsyncClient, *, min_interval: float = DEFAULT_MIN_INTERVAL_SEC,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 now: Callable[[], datetime] | None = None, user_agent: str = USER_AGENT) -> None:
        self.client = client
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(UTC))
        self.user_agent = user_agent
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_start: dict[str, float] = {}

    async def get(self, url: str, *, params: Mapping[str, Any] | None = None,
                  validators: Validators | None = None, accept: str | None = "application/json",
                  max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = DEFAULT_TIMEOUT_SEC) -> FetchResult:
        host = httpx.URL(url).host
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last_start.get(host)
            if last is not None and self.min_interval > 0:
                wait = last + self.min_interval - self.clock()
                if wait > 0:
                    await self.sleep(wait)
            self._last_start[host] = self.clock()
            return await self._fetch(url, params, validators, accept, max_bytes, timeout)

    def _headers(self, validators: Validators | None, accept: str | None) -> dict[str, str]:
        headers = {"user-agent": self.user_agent}
        if accept:
            headers["accept"] = accept
        if validators is not None:
            if validators.etag:
                headers["if-none-match"] = validators.etag
            if validators.last_modified:
                headers["if-modified-since"] = validators.last_modified
        return headers

    async def _fetch(self, url: str, params: Mapping[str, Any] | None, validators: Validators | None,
                     accept: str | None, max_bytes: int, timeout: float) -> FetchResult:
        previous = validators or Validators()
        async with self.client.stream("GET", url, params=params, headers=self._headers(validators, accept),
                                      timeout=timeout, follow_redirects=False) as response:
            status = response.status_code
            retry_after = parse_retry_after(response.headers.get("retry-after"), self.now())
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            if status == 304:
                kept = Validators(etag=etag or previous.etag, last_modified=last_modified or previous.last_modified,
                                  body_hash=previous.body_hash)
                return FetchResult(status, None, kept, not_modified=True, retry_after=retry_after)
            if status == 429 or (status == 503 and retry_after is not None):
                raise RateLimited(retry_after, status)
            if not 200 <= status < 300:
                raise HttpStatusError(status)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > max_bytes:
                    raise ResponseTooLarge(max_bytes)
                body.extend(chunk)
        digest = hashlib.sha256(body).hexdigest()
        unchanged = (etag is None and last_modified is None and validators is not None
                     and validators.body_hash == digest)
        return FetchResult(status, None if unchanged else bytes(body),
                           Validators(etag=etag, last_modified=last_modified, body_hash=digest),
                           not_modified=unchanged, retry_after=retry_after)
