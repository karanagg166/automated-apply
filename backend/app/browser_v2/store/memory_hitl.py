"""MemoryStore HITL inbox, digest-day claim and Telegram state (mixin)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.records import (
    ANSWER_KINDS,
    REF_PATTERN,
    HitlRecord,
    _now,
    _telegram_changes,
)


class MemoryHitlMixin(MemoryBase):
    async def create_hitl(self, record, platform, kind, prompt, context):
        hitl_id = str(uuid.uuid4())
        self.hitl.append({"id": hitl_id, "application_id": record.id if record else None,
                          "platform": platform, "kind": kind, "prompt": prompt, "context": context,
                          "status": "OPEN", "telegram_msg_id": None, "answer_text": None,
                          "created_at": _now(), "resolved_at": None, "resolved_via": None,
                          "consumed_at": None})
        return hitl_id

    def _hitl_record(self, row: dict[str, Any]) -> HitlRecord:
        app = next((r for r in self.records.values() if r.id == row.get("application_id")), None)
        return HitlRecord(
            id=row["id"], platform=row["platform"], kind=row["kind"], prompt_text=row["prompt"],
            status=row["status"], application_id=row.get("application_id"),
            context=dict(row.get("context") or {}), telegram_msg_id=row.get("telegram_msg_id"),
            answer_text=row.get("answer_text"), created_at=row.get("created_at"),
            resolved_at=row.get("resolved_at"), resolved_via=row.get("resolved_via"),
            consumed_at=row.get("consumed_at"), company_name=app.company_name if app else None,
            role_title=app.role_title if app else None, job_url=app.job_url if app else None,
            application_state=app.state.value if app else None,
            telegram_card_closed_at=row.get("telegram_card_closed_at"))

    async def get_hitl(self, hitl_id):
        row = next((h for h in self.hitl if h.get("id") == hitl_id), None)
        return self._hitl_record(row) if row else None

    async def find_open_hitl_by_ref(self, ref):
        ref = (ref or "").lower().replace("-", "")
        if not REF_PATTERN.match(ref):
            return []
        return [self._hitl_record(h) for h in self.hitl
                if h["status"] == "OPEN" and h["id"].replace("-", "").startswith(ref)]

    async def find_hitl_by_message(self, message_id):
        row = next((h for h in self.hitl if h.get("telegram_msg_id") == message_id), None)
        return self._hitl_record(row) if row else None

    async def list_hitl(self, status="OPEN", platform=None, limit=50, offset=0):
        rows = [h for h in self.hitl if (status is None or h["status"] == status)
                and (platform is None or h["platform"] == platform)]
        rows.sort(key=lambda h: h["created_at"])
        return [self._hitl_record(h) for h in rows[offset: offset + limit]], len(rows)

    async def undelivered_hitl(self, limit=10):
        rows = [h for h in self.hitl if h["status"] == "OPEN" and h.get("telegram_msg_id") is None]
        return [self._hitl_record(h) for h in sorted(rows, key=lambda h: h["created_at"])[:limit]]

    async def mark_hitl_delivered(self, hitl_id, message_id):
        for row in self.hitl:
            if row.get("id") == hitl_id and row.get("telegram_msg_id") is None:
                row["telegram_msg_id"] = message_id

    async def close_hitl(self, hitl_id, status, answer_text, via):
        row = next((h for h in self.hitl if h.get("id") == hitl_id), None)
        if row is None or row["status"] != "OPEN":
            return None  # already resolved elsewhere (double click / dashboard race)
        row.update(status=status, answer_text=answer_text, resolved_at=_now(), resolved_via=via)
        return self._hitl_record(row)

    async def count_open_hitl(self, platform=None):
        return sum(1 for h in self.hitl if h["status"] == "OPEN"
                   and (platform is None or h["platform"] == platform))

    async def expire_stale_hitl(self, kind, older_than):
        expired = []
        for row in self.hitl:
            if row["status"] == "OPEN" and row["kind"] == kind and row["created_at"] < older_than:
                row["status"], row["resolved_at"], row["resolved_via"] = "EXPIRED", _now(), "worker"
                expired.append(self._hitl_record(row))
        return expired

    async def claim_digest_day(self, day):
        if self.telegram.last_digest_on == day:
            return False
        self.telegram.last_digest_on = day
        return True

    async def release_digest_day(self, day, previous):
        if self.telegram.last_digest_on == day:
            self.telegram.last_digest_on = previous

    async def requeued_applications(self, platform, limit=20):
        now = _now()
        pending = {h["application_id"] for h in self.hitl
                   if h["status"] == "ANSWERED" and h.get("consumed_at") is None and h.get("application_id")}
        rows = [replace(r) for (p, _), r in self.records.items()
                if p == platform and r.state == ApplicationState.SCORED and r.id in pending
                and (r.retry_after is None or r.retry_after <= now)]
        rows.sort(key=lambda r: r.retry_after or r.updated_at or now)
        return rows[:limit]

    async def hitl_answers(self, application_id):
        rows = [h for h in self.hitl if h.get("application_id") == application_id
                and h["status"] == "ANSWERED" and h["kind"] in ANSWER_KINDS and h.get("answer_text")]
        rows.sort(key=lambda h: h["resolved_at"] or h["created_at"])
        return {h["prompt"]: h["answer_text"] for h in rows}

    async def mark_hitl_consumed(self, application_id):
        count = 0
        for row in self.hitl:
            if row.get("application_id") == application_id and row["status"] == "ANSWERED" \
                    and row.get("consumed_at") is None:
                row["consumed_at"], count = _now(), count + 1
        return count

    async def get_telegram_state(self):
        return replace(self.telegram)

    async def update_telegram_state(self, **changes):
        for key, value in _telegram_changes(changes).items():
            setattr(self.telegram, key, value)
        self.telegram.updated_at = _now()
        return replace(self.telegram)

    async def open_hitl_exists(self, platform, kind):
        return any(h["platform"] == platform and h["kind"] == kind and h["status"] == "OPEN"
                   for h in self.hitl)

    async def cancel_open_hitl(self, platform, kind):
        count = 0
        for item in self.hitl:
            if item["platform"] == platform and item["kind"] == kind and item["status"] == "OPEN":
                item["status"], count = "CANCELLED", count + 1
        return count
