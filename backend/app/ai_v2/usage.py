"""Per-(provider, model) minute/day usage buckets + circuit state (public.llm_provider_usage).

The circuit (`circuit_open_until`, `last_error`) is stored on the current day
row so a restarted worker still skips a provider that is cooling down.
`last_error` only ever holds an error class (`http_429`, `timeout`, ...),
never response bodies or prompt text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class UsageSnapshot:
    minute_requests: int = 0
    day_requests: int = 0
    day_input_tokens: int = 0
    day_output_tokens: int = 0
    circuit_open_until: datetime | None = None
    last_error: str | None = None

    @property
    def day_tokens(self) -> int:
        return self.day_input_tokens + self.day_output_tokens


def minute_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(second=0, microsecond=0)


def day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class UsageStore(Protocol):
    backend: str

    async def snapshot(self, provider: str, model: str, now: datetime) -> UsageSnapshot: ...

    async def record(self, provider: str, model: str, now: datetime, *, requests: int = 0,
                     input_tokens: int = 0, output_tokens: int = 0) -> None: ...

    async def set_circuit(self, provider: str, model: str, now: datetime, open_until: datetime | None,
                          error: str | None) -> None: ...


@dataclass
class _Bucket:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    circuit_open_until: datetime | None = None
    last_error: str | None = None


class MemoryUsageStore:
    backend = "memory"

    def __init__(self) -> None:
        self.buckets: dict[tuple[str, str, str, datetime], _Bucket] = {}

    def _bucket(self, provider: str, model: str, window: str, start: datetime) -> _Bucket:
        return self.buckets.setdefault((provider, model, window, start), _Bucket())

    async def snapshot(self, provider, model, now):
        minute = self.buckets.get((provider, model, "minute", minute_start(now)), _Bucket())
        day = self.buckets.get((provider, model, "day", day_start(now)), _Bucket())
        return UsageSnapshot(minute.requests, day.requests, day.input_tokens, day.output_tokens,
                             day.circuit_open_until, day.last_error)

    async def record(self, provider, model, now, *, requests=0, input_tokens=0, output_tokens=0):
        for window, start in (("minute", minute_start(now)), ("day", day_start(now))):
            bucket = self._bucket(provider, model, window, start)
            bucket.requests += requests
            bucket.input_tokens += input_tokens
            bucket.output_tokens += output_tokens

    async def set_circuit(self, provider, model, now, open_until, error):
        bucket = self._bucket(provider, model, "day", day_start(now))
        bucket.circuit_open_until = open_until
        bucket.last_error = error


RECORD_SQL = """
INSERT INTO public.llm_provider_usage
    (provider, model, window_type, window_start, requests, input_tokens, output_tokens)
VALUES ($1, $2, 'minute', $3, $5, $6, $7), ($1, $2, 'day', $4, $5, $6, $7)
ON CONFLICT (provider, model, window_type, window_start) DO UPDATE SET
    requests = public.llm_provider_usage.requests + EXCLUDED.requests,
    input_tokens = public.llm_provider_usage.input_tokens + EXCLUDED.input_tokens,
    output_tokens = public.llm_provider_usage.output_tokens + EXCLUDED.output_tokens
"""
CIRCUIT_SQL = """
INSERT INTO public.llm_provider_usage (provider, model, window_type, window_start, circuit_open_until, last_error)
VALUES ($1, $2, 'day', $3, $4, $5)
ON CONFLICT (provider, model, window_type, window_start) DO UPDATE SET
    circuit_open_until = EXCLUDED.circuit_open_until, last_error = EXCLUDED.last_error
"""
SNAPSHOT_SQL = """
SELECT window_type, requests, input_tokens, output_tokens, circuit_open_until, last_error
FROM public.llm_provider_usage
WHERE provider = $1 AND model = $2
  AND ((window_type = 'minute' AND window_start = $3) OR (window_type = 'day' AND window_start = $4))
"""


class PostgresUsageStore:
    backend = "postgres"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def snapshot(self, provider, model, now):
        rows = await self.connection.fetch(SNAPSHOT_SQL, provider, model, minute_start(now), day_start(now))
        minute = next((r for r in rows if r["window_type"] == "minute"), None)
        day = next((r for r in rows if r["window_type"] == "day"), None)
        return UsageSnapshot(
            minute_requests=minute["requests"] if minute else 0,
            day_requests=day["requests"] if day else 0,
            day_input_tokens=day["input_tokens"] if day else 0,
            day_output_tokens=day["output_tokens"] if day else 0,
            circuit_open_until=day["circuit_open_until"] if day else None,
            last_error=day["last_error"] if day else None)

    async def record(self, provider, model, now, *, requests=0, input_tokens=0, output_tokens=0):
        await self.connection.execute(RECORD_SQL, provider, model, minute_start(now), day_start(now),
                                      requests, input_tokens, output_tokens)

    async def set_circuit(self, provider, model, now, open_until, error):
        await self.connection.execute(CIRCUIT_SQL, provider, model, day_start(now), open_until,
                                      (error or None) and error[:200])
