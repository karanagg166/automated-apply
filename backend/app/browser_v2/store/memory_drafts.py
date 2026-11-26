"""MemoryStore email drafts (mixin)."""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.records import (
    BODY_PREVIEW_CHARS,
    DRAFT_CHANNELS,
    DraftReservation,
    EmailDraftRecord,
    _clip,
    _now,
)


class MemoryDraftsMixin(MemoryBase):
    def _draft_record(self, row: dict[str, Any]) -> EmailDraftRecord:
        app = next((r for r in self.records.values() if r.id == row.get("application_id")), None)
        known = set(EmailDraftRecord.__dataclass_fields__)
        values = {k: v for k, v in row.items() if k in known}
        return EmailDraftRecord(**values, company_name=app.company_name if app else None,
                                role_title=app.role_title if app else None,
                                application_state=app.state.value if app else None,
                                retry_after=app.retry_after if app else None)

    async def reserve_email_draft(self, application_id, platform, recipient_email):
        existing = next((d for d in self.drafts if d["application_id"] == application_id), None)
        if existing is not None:
            if existing["status"] != "FAILED":
                return DraftReservation(False, self._draft_record(existing))
            existing.update(status="PENDING", recipient_email=recipient_email, last_error=None,
                            updated_at=_now())  # a definite failure may be retried once more
            return DraftReservation(True, self._draft_record(existing))
        row = {"id": str(uuid.uuid4()), "application_id": application_id, "platform": platform,
               "recipient_email": recipient_email, "status": "PENDING", "created_at": _now(),
               "updated_at": _now()}
        self.drafts.append(row)
        return DraftReservation(True, self._draft_record(row))

    async def complete_email_draft(self, draft_id, *, channel, subject, body_preview, composer,
                                   enrichment_source, external_draft_id):
        if channel not in DRAFT_CHANNELS:
            raise ValueError("invalid draft channel")
        row = next(d for d in self.drafts if d["id"] == draft_id)
        row.update(status="CREATED", channel=channel, subject=subject,
                   body_preview=_clip(body_preview, BODY_PREVIEW_CHARS), composer=composer,
                   enrichment_source=enrichment_source, external_draft_id=external_draft_id,
                   last_error=None, created_at=_now(), updated_at=_now())
        for record in self.records.values():
            if record.id == row["application_id"] and record.draft_created_at is None:
                record.draft_created_at = _now()
        return self._draft_record(row)

    async def fail_email_draft(self, draft_id, error, *, ambiguous=False):
        row = next((d for d in self.drafts if d["id"] == draft_id), None)
        if row is not None:
            row.update(last_error=_clip(error, 200), updated_at=_now(),
                       status="PENDING" if ambiguous else "FAILED")

    async def get_email_draft(self, application_id):
        row = next((d for d in self.drafts if d["application_id"] == application_id), None)
        return self._draft_record(row) if row else None

    async def list_email_drafts(self, platform=None, limit=50, offset=0):
        rows = [d for d in self.drafts if platform is None or d.get("platform") == platform]
        rows.sort(key=lambda d: d["created_at"], reverse=True)
        return [self._draft_record(d) for d in rows[offset: offset + limit]], len(rows)

    async def count_email_drafts(self, status="CREATED", platform=None, since=None):
        return sum(1 for d in self.drafts if d["status"] == status
                   and (platform is None or d.get("platform") == platform)
                   and (since is None or d["created_at"] >= since))
