"""PostgresStore agent audit log (followup 005): append-only insert + recent rows."""

from __future__ import annotations

import json

from backend.app.browser_v2.store.agent_records import AuditEntry
from backend.app.browser_v2.store.base import PostgresBase

AUDIT_COLUMNS = "id, source, tool_name, args, before_summary, after_summary, outcome, error, created_at"


def _dump(value: object) -> str | None:
    return None if value is None else json.dumps(value, default=str)


class AuditRepo(PostgresBase):
    async def append_audit(self, entry: AuditEntry) -> AuditEntry:
        """INSERT only: the runtime role has SELECT + INSERT on agent_audit_log (no UPDATE/DELETE)."""
        row = await self.connection.fetchrow(
            f"""INSERT INTO public.agent_audit_log
                    (source, tool_name, args, before_summary, after_summary, outcome, error)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7)
                RETURNING {AUDIT_COLUMNS}""",
            entry.source, entry.tool_name, _dump(entry.args or {}), _dump(entry.before_summary),
            _dump(entry.after_summary), entry.outcome, entry.error)
        return AuditEntry.from_row(row)

    async def list_audit(self, limit: int = 20, tool_name: str | None = None) -> list[AuditEntry]:
        rows = await self.connection.fetch(
            f"""SELECT {AUDIT_COLUMNS} FROM public.agent_audit_log
                WHERE ($1::text IS NULL OR tool_name = $1)
                ORDER BY created_at DESC, id LIMIT $2""",
            tool_name, max(1, min(int(limit), 200)))
        return [AuditEntry.from_row(row) for row in rows]
