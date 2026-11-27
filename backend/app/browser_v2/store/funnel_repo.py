"""Milestone 2: post-apply mail funnel + owner reconciliation reads/writes (PostgreSQL).

`annotate_application` appends a same-state timeline event (from_state = to_state) and merges a
receipt patch WITHOUT touching state, applied_at or updated_at, so it never re-counts quota, never
re-orders the queue and never resets the 24 h `needs_reconciliation` clock. The MemoryStore twin is
`memory_funnel.MemoryFunnelMixin`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.base import PostgresBase, _record
from backend.app.browser_v2.store.records import ApplicationRecord

# Rows a confirmation / OA / interview / rejection mail may belong to.
MAIL_MATCH_STATES = ("APPLIED", "SUBMISSION_UNKNOWN")


class FunnelRepo(PostgresBase):
    async def annotate_application(self, application_id: str, event_type: str, payload: dict[str, Any] | None = None,
                                   receipt_patch: dict[str, Any] | None = None) -> ApplicationRecord | None:
        async with self.connection.transaction():
            row = await self.connection.fetchrow(
                f"""UPDATE public.applications
                       SET receipt = COALESCE(receipt, '{{}}'::jsonb) || COALESCE($2::jsonb, '{{}}'::jsonb),
                           version = version + CASE WHEN $2::jsonb IS NULL THEN 0 ELSE 1 END
                     WHERE id = $1::uuid RETURNING {self.COLUMNS}""",
                application_id, json.dumps(receipt_patch, default=str) if receipt_patch else None)
            if row is None:
                return None
            await self.connection.execute(
                """INSERT INTO public.application_state_events
                       (application_id, from_state, to_state, event_type, payload)
                   VALUES ($1::uuid, $2, $2, $3, $4::jsonb)""",
                application_id, row["state"], event_type[:80], json.dumps(payload or {}, default=str))
        return _record(row)

    async def mail_match_candidates(self, since: datetime, limit: int = 500) -> list[ApplicationRecord]:
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE state = ANY($1::text[]) AND COALESCE(applied_at, updated_at) >= $2
                ORDER BY COALESCE(applied_at, updated_at) DESC LIMIT $3""",
            list(MAIL_MATCH_STATES), since, limit)
        return [_record(r) for r in rows]

    async def needs_reconciliation(self, older_than: datetime, limit: int = 100) -> list[ApplicationRecord]:
        """SUBMISSION_UNKNOWN rows untouched since `older_than` (a confirmation mail would have made
        them APPLIED): the owner verifies them in the portal or releases the quota slot."""
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE state = $1 AND updated_at < $2 ORDER BY updated_at LIMIT $3""",
            ApplicationState.SUBMISSION_UNKNOWN.value, older_than, limit)
        return [_record(r) for r in rows]
