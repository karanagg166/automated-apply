"""``public.profile_sync_runs`` persistence (followup 005) without touching the store package.

``PostgresProfileSyncRuns`` reuses the v2 store's single connection (``store.connection``,
the SerializedConnection of the worker or the API's borrowed pooled connection); it never
opens a connection of its own. ``MemoryProfileSyncRuns`` backs the MemoryStore (dry runs,
tests). ``fields`` / ``receipt`` only ever hold statuses and SHA-256 references.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from backend.app.browser_v2.profile_sync.models import (
    PLATFORM_PATTERN,
    RUN_STATUSES,
    TRIGGERS,
    clip_error,
)

MEMORY_ATTRIBUTE = "_profile_sync_runs"
COLUMNS = ("id, platform, trigger, dry_run, status, fields::text AS fields, error, receipt::text AS receipt, "
           "started_at, finished_at")


def _now() -> datetime:
    return datetime.now(UTC)


def check_start(platform: str, trigger: str) -> None:
    if not PLATFORM_PATTERN.match(platform or ""):
        raise ValueError(f"invalid_platform:{platform!r}")
    if trigger not in TRIGGERS:
        raise ValueError(f"invalid_trigger:{trigger!r}")


def check_status(status: str) -> None:
    if status not in RUN_STATUSES or status == "running":
        raise ValueError(f"invalid_final_status:{status!r}")


@runtime_checkable
class ProfileSyncRuns(Protocol):
    async def start(self, platform: str, trigger: str, dry_run: bool) -> str: ...

    async def finish(self, run_id: str, status: str, fields: Mapping[str, Any], error: str | None = None,
                     receipt: Mapping[str, Any] | None = None) -> None: ...

    async def last(self, platform: str) -> dict[str, Any] | None: ...

    async def last_freshness_touch(self, platform: str) -> datetime | None: ...


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _row(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["id"] = str(data["id"])
    data["fields"] = _loads(data.get("fields")) or {}
    data["receipt"] = _loads(data.get("receipt"))
    return data


class PostgresProfileSyncRuns:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def ready(self) -> bool:
        return bool(await self.connection.fetchval("SELECT to_regclass('public.profile_sync_runs') IS NOT NULL"))

    async def start(self, platform: str, trigger: str, dry_run: bool) -> str:
        check_start(platform, trigger)
        run_id = await self.connection.fetchval(
            "INSERT INTO public.profile_sync_runs (platform, trigger, dry_run) VALUES ($1, $2, $3) RETURNING id",
            platform, trigger, bool(dry_run))
        return str(run_id)

    async def finish(self, run_id: str, status: str, fields: Mapping[str, Any], error: str | None = None,
                     receipt: Mapping[str, Any] | None = None) -> None:
        check_status(status)
        await self.connection.execute(
            "UPDATE public.profile_sync_runs SET status=$2, fields=$3::jsonb, error=$4, receipt=$5::jsonb, "
            "finished_at=now() WHERE id=$1::uuid",
            run_id, status, json.dumps(dict(fields), default=str), clip_error(error),
            json.dumps(dict(receipt), default=str) if receipt is not None else None)

    async def last(self, platform: str) -> dict[str, Any] | None:
        row = await self.connection.fetchrow(
            f"SELECT {COLUMNS} FROM public.profile_sync_runs WHERE platform=$1 "
            "ORDER BY started_at DESC LIMIT 1", platform)
        return _row(row) if row is not None else None

    async def last_freshness_touch(self, platform: str) -> datetime | None:
        value = await self.connection.fetchval(
            "SELECT max(finished_at) FROM public.profile_sync_runs WHERE platform=$1 AND dry_run=false "
            "AND receipt->>'freshness_touched' = 'true'", platform)
        return value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value


class MemoryProfileSyncRuns:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or _now
        self.rows: list[dict[str, Any]] = []

    async def start(self, platform: str, trigger: str, dry_run: bool) -> str:
        check_start(platform, trigger)
        row = {"id": str(uuid.uuid4()), "platform": platform, "trigger": trigger, "dry_run": bool(dry_run),
               "status": "running", "fields": {}, "error": None, "receipt": None,
               "started_at": self.clock(), "finished_at": None}
        self.rows.append(row)
        return str(row["id"])

    async def finish(self, run_id: str, status: str, fields: Mapping[str, Any], error: str | None = None,
                     receipt: Mapping[str, Any] | None = None) -> None:
        check_status(status)
        for row in self.rows:
            if row["id"] == run_id:
                # JSON round trip: exactly what Postgres would store (and proves it is serialisable).
                row.update(status=status, fields=json.loads(json.dumps(dict(fields), default=str)),
                           error=clip_error(error), finished_at=self.clock(),
                           receipt=json.loads(json.dumps(dict(receipt), default=str))
                           if receipt is not None else None)
                return
        raise KeyError(run_id)

    async def last(self, platform: str) -> dict[str, Any] | None:
        rows = [row for row in self.rows if row["platform"] == platform]
        return dict(max(rows, key=lambda row: row["started_at"])) if rows else None

    async def last_freshness_touch(self, platform: str) -> datetime | None:
        touched = [row["finished_at"] for row in self.rows
                   if row["platform"] == platform and not row["dry_run"] and row["finished_at"] is not None
                   and (row.get("receipt") or {}).get("freshness_touched") is True]
        return max(touched) if touched else None


def runs_for(store: Any, *, clock: Callable[[], datetime] | None = None) -> ProfileSyncRuns:
    """Postgres runs on the store's own connection; else one MemoryProfileSyncRuns per store object."""
    connection = getattr(store, "connection", None)
    if connection is not None:
        return PostgresProfileSyncRuns(connection)
    existing = getattr(store, MEMORY_ATTRIBUTE, None)
    if isinstance(existing, MemoryProfileSyncRuns):
        return existing
    runs = MemoryProfileSyncRuns(clock)
    try:
        setattr(store, MEMORY_ATTRIBUTE, runs)
    except AttributeError:  # a slotted/frozen store: still usable for this call
        pass
    return runs
