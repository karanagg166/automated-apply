"""MemoryStore twin of `funnel_repo.FunnelRepo` (same contract, same ordering)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.records import ApplicationRecord, _now

MAIL_MATCH_STATES = (ApplicationState.APPLIED, ApplicationState.SUBMISSION_UNKNOWN)


class MemoryFunnelMixin(MemoryBase):
    async def annotate_application(self, application_id: str, event_type: str, payload: dict[str, Any] | None = None,
                                   receipt_patch: dict[str, Any] | None = None) -> ApplicationRecord | None:
        current = next((r for r in self.records.values() if r.id == application_id), None)
        if current is None:
            return None
        if receipt_patch:
            current.receipt = dict(current.receipt or {}) | dict(receipt_patch)
            current.version += 1
        self.events.append({"application_id": current.id, "from": current.state, "to": current.state,
                            "reason": event_type[:80], "payload": dict(payload or {}), "created_at": _now()})
        return replace(current)

    async def mail_match_candidates(self, since: datetime, limit: int = 500) -> list[ApplicationRecord]:
        def moment(r: ApplicationRecord) -> datetime:
            return r.applied_at or r.updated_at or _now()

        rows = [replace(r) for r in self.records.values() if r.state in MAIL_MATCH_STATES and moment(r) >= since]
        rows.sort(key=moment, reverse=True)
        return rows[:limit]

    async def needs_reconciliation(self, older_than: datetime, limit: int = 100) -> list[ApplicationRecord]:
        rows = [replace(r) for r in self.records.values() if r.state == ApplicationState.SUBMISSION_UNKNOWN
                and (r.updated_at or _now()) < older_than]
        rows.sort(key=lambda r: r.updated_at or _now())
        return rows[:limit]
