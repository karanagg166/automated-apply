"""PostgresStore fast-poll watcher state and the followup-005 readiness probe (mixin over PostgresBase)."""

from __future__ import annotations

import json

from backend.app.browser_v2.store.base import PostgresBase
from backend.app.browser_v2.store.phase9_records import WatcherState
from backend.app.operations.v2_schema import PHASE9_COLUMNS, PHASE9_TABLES

WATCHER_FIELDS = ("source", "etag", "last_modified", "body_hash", "seen_ids", "baseline_at", "last_poll_at",
                  "next_poll_at", "last_status", "failures", "open_until", "last_error", "budget_day",
                  "budget_used")


class WatcherRepo(PostgresBase):
    async def get_watcher_state(self, source: str) -> WatcherState | None:
        row = await self.connection.fetchrow(
            f"SELECT {', '.join(WATCHER_FIELDS)}, updated_at FROM public.watcher_state WHERE source=$1", source)
        return WatcherState.from_row(dict(row)) if row else None

    async def save_watcher_state(self, state: WatcherState) -> WatcherState:
        placeholders = ", ".join(f"${i + 1}" + ("::jsonb" if name == "seen_ids" else "")
                                 for i, name in enumerate(WATCHER_FIELDS))
        updates = ", ".join(f"{name}=EXCLUDED.{name}" for name in WATCHER_FIELDS[1:])
        values = [json.dumps(list(state.seen_ids)) if name == "seen_ids" else getattr(state, name)
                  for name in WATCHER_FIELDS]
        row = await self.connection.fetchrow(
            f"""INSERT INTO public.watcher_state ({', '.join(WATCHER_FIELDS)}) VALUES ({placeholders})
                ON CONFLICT (source) DO UPDATE SET {updates}, updated_at=now()
                RETURNING {', '.join(WATCHER_FIELDS)}, updated_at""", *values)
        return WatcherState.from_row(dict(row))

    async def phase9_ready(self) -> bool:
        """Read-only: followup 005 tables and the columns it adds to 004 tables all exist."""
        expected = sum(len(columns) for columns in PHASE9_COLUMNS.values())
        try:
            return bool(await self.connection.fetchval(
                """SELECT (SELECT bool_and(to_regclass('public.' || t) IS NOT NULL) FROM unnest($1::text[]) AS t)
                      AND (SELECT count(*) FROM pg_attribute
                           WHERE NOT attisdropped AND attnum > 0
                             AND ((attrelid = to_regclass('public.applications') AND attname = ANY($2::text[]))
                               OR (attrelid = to_regclass('public.portal_rules') AND attname = ANY($3::text[]))))
                          = $4""",
                sorted(PHASE9_TABLES), list(PHASE9_COLUMNS["applications"]), list(PHASE9_COLUMNS["portal_rules"]),
                expected))
        except Exception:  # noqa: BLE001 - a probe: any catalog/permission error means "not ready"
            return False
