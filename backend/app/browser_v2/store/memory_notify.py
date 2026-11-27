"""MemoryStore twin of followup 007 (NotifyRepo): same semantics, for tests and dry runs."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.app.browser_v2.store.notify_records import (
    DigestItem,
    LedgerEntry,
    bound_digest_text,
    check_dedup_key,
)
from backend.app.browser_v2.store.records import _now


class MemoryNotifyMixin:
    hitl: list[dict[str, Any]]

    def _notify_state(self) -> tuple[dict[str, LedgerEntry], list[dict[str, Any]]]:
        if not hasattr(self, "_ledger"):
            self._ledger: dict[str, LedgerEntry] = {}
            self._digest: list[dict[str, Any]] = []
        return self._ledger, self._digest

    async def ledger_get(self, dedup_key: str) -> LedgerEntry | None:
        ledger, _ = self._notify_state()
        entry = ledger.get(check_dedup_key(dedup_key))
        return replace(entry) if entry else None

    async def ledger_record(self, dedup_key: str, *, topic: str, priority: int, now: datetime,
                            sent: bool, suppressed: bool = False, chat_id: int | None = None,
                            message_id: int | None = None) -> LedgerEntry:
        ledger, _ = self._notify_state()
        entry = ledger.get(check_dedup_key(dedup_key)) or LedgerEntry(dedup_key, topic, priority)
        entry.topic, entry.priority, entry.last_event_at = topic, priority, now
        if sent:
            entry.last_sent_at, entry.suppressed_count, entry.message_id, entry.resolved_at = now, 0, message_id, None
        elif suppressed:
            entry.suppressed_count += 1
        if chat_id is not None:
            entry.chat_id = chat_id
        ledger[dedup_key] = entry
        return replace(entry)

    async def ledger_resolve(self, dedup_key: str, now: datetime) -> LedgerEntry | None:
        ledger, _ = self._notify_state()
        entry = ledger.get(check_dedup_key(dedup_key))
        if entry is None or entry.resolved_at is not None:
            return None
        entry.resolved_at = now
        return replace(entry)

    async def digest_enqueue(self, topic: str, priority: int, text: str, dedup_key: str | None = None) -> None:
        _, digest = self._notify_state()
        digest.append({"id": str(uuid.uuid4()), "topic": topic, "priority": priority,
                       "dedup_key": check_dedup_key(dedup_key) if dedup_key else None,
                       "text": bound_digest_text(text), "created_at": _now(), "delivered_at": None})

    async def digest_pending(self, limit: int = 200) -> list[DigestItem]:
        _, digest = self._notify_state()
        rows = sorted((r for r in digest if r["delivered_at"] is None), key=lambda r: (r["priority"], r["created_at"]))
        return [DigestItem(id=r["id"], topic=r["topic"], priority=r["priority"], text=r["text"],
                           dedup_key=r["dedup_key"], created_at=r["created_at"]) for r in rows[:limit]]

    async def digest_mark_delivered(self, ids: list[str], now: datetime) -> int:
        _, digest = self._notify_state()
        marked = 0
        for row in digest:
            if row["id"] in ids and row["delivered_at"] is None:
                row["delivered_at"] = now
                marked += 1
        return marked

    async def claim_digest_slot(self, slot: str, previous: str | None) -> bool:
        telegram = self.telegram  # type: ignore[attr-defined]
        if telegram.last_digest_slot != previous:
            return False
        telegram.last_digest_slot = slot
        return True

    async def unsynced_closed_hitl(self, limit: int = 10) -> list[Any]:
        rows = [h for h in self.hitl if h["status"] != "OPEN" and h.get("telegram_msg_id") is not None
                and h.get("telegram_card_closed_at") is None]
        rows.sort(key=lambda h: h.get("resolved_at") or _now())
        return [self._hitl_record(h) for h in rows[:limit]]  # type: ignore[attr-defined]

    async def mark_hitl_card_closed(self, hitl_id: str) -> None:
        for row in self.hitl:
            if row.get("id") == hitl_id and row.get("telegram_card_closed_at") is None:
                row["telegram_card_closed_at"] = _now()
