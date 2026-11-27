"""PostgresStore followup 007: notification ledger, digest queue and HITL card sync."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.browser_v2.store.base import PostgresBase, _hitl
from backend.app.browser_v2.store.notify_records import (
    DigestItem,
    LedgerEntry,
    bound_digest_text,
    check_dedup_key,
)

LEDGER_COLUMNS = ("dedup_key, topic, priority, last_event_at, last_sent_at, suppressed_count, chat_id, "
                  "message_id, resolved_at")


def _ledger(row: Any) -> LedgerEntry:
    return LedgerEntry(**{k: row[k] for k in LEDGER_COLUMNS.split(", ")})


class NotifyRepo(PostgresBase):
    async def ledger_get(self, dedup_key: str) -> LedgerEntry | None:
        row = await self.connection.fetchrow(
            f"SELECT {LEDGER_COLUMNS} FROM public.telegram_notification_ledger WHERE dedup_key=$1",
            check_dedup_key(dedup_key))
        return _ledger(row) if row else None

    async def ledger_record(self, dedup_key: str, *, topic: str, priority: int, now: datetime,
                            sent: bool, suppressed: bool = False, chat_id: int | None = None,
                            message_id: int | None = None) -> LedgerEntry:
        """Upsert: a send resets the suppressed counter and (re)opens the card; a suppression counts."""
        row = await self.connection.fetchrow(
            f"""INSERT INTO public.telegram_notification_ledger
                    (dedup_key, topic, priority, last_event_at, last_sent_at, suppressed_count, chat_id, message_id)
                VALUES ($1, $2, $3, $4::timestamptz, CASE WHEN $5::boolean THEN $4::timestamptz END,
                        CASE WHEN $6::boolean THEN 1 ELSE 0 END, $7::bigint, $8::bigint)
                ON CONFLICT (dedup_key) DO UPDATE SET
                    topic=EXCLUDED.topic, priority=EXCLUDED.priority, last_event_at=$4::timestamptz,
                    last_sent_at=CASE WHEN $5::boolean THEN $4::timestamptz
                                      ELSE telegram_notification_ledger.last_sent_at END,
                    suppressed_count=CASE WHEN $5::boolean THEN 0
                                          WHEN $6::boolean THEN telegram_notification_ledger.suppressed_count + 1
                                          ELSE telegram_notification_ledger.suppressed_count END,
                    chat_id=COALESCE($7::bigint, telegram_notification_ledger.chat_id),
                    message_id=CASE WHEN $5::boolean THEN $8::bigint ELSE telegram_notification_ledger.message_id END,
                    resolved_at=CASE WHEN $5::boolean THEN NULL ELSE telegram_notification_ledger.resolved_at END,
                    updated_at=now()
                RETURNING {LEDGER_COLUMNS}""",
            check_dedup_key(dedup_key), topic, priority, now, sent, suppressed, chat_id, message_id)
        return _ledger(row)

    async def ledger_resolve(self, dedup_key: str, now: datetime) -> LedgerEntry | None:
        row = await self.connection.fetchrow(
            f"""UPDATE public.telegram_notification_ledger SET resolved_at=$2, updated_at=now()
                WHERE dedup_key=$1 AND resolved_at IS NULL RETURNING {LEDGER_COLUMNS}""",
            check_dedup_key(dedup_key), now)
        return _ledger(row) if row else None

    async def digest_enqueue(self, topic: str, priority: int, text: str, dedup_key: str | None = None) -> None:
        await self.connection.execute(
            """INSERT INTO public.telegram_digest_queue (topic, priority, dedup_key, text)
               VALUES ($1, $2, $3, $4)""",
            topic, priority, check_dedup_key(dedup_key) if dedup_key else None, bound_digest_text(text))

    async def digest_pending(self, limit: int = 200) -> list[DigestItem]:
        rows = await self.connection.fetch(
            """SELECT id, topic, priority, text, dedup_key, created_at FROM public.telegram_digest_queue
               WHERE delivered_at IS NULL ORDER BY priority, created_at LIMIT $1""", limit)
        return [DigestItem(id=str(r["id"]), topic=r["topic"], priority=r["priority"], text=r["text"],
                           dedup_key=r["dedup_key"], created_at=r["created_at"]) for r in rows]

    async def digest_mark_delivered(self, ids: list[str], now: datetime) -> int:
        if not ids:
            return 0
        result = await self.connection.execute(
            """UPDATE public.telegram_digest_queue SET delivered_at=$2
               WHERE id = ANY($1::uuid[]) AND delivered_at IS NULL""", ids, now)
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    async def claim_digest_slot(self, slot: str, previous: str | None) -> bool:
        await self.connection.execute(
            """INSERT INTO public.telegram_v2_state (singleton_key) VALUES ('primary')
               ON CONFLICT (singleton_key) DO NOTHING""")
        claimed = await self.connection.fetchval(
            """UPDATE public.telegram_v2_state SET last_digest_slot=$1, updated_at=now()
               WHERE singleton_key='primary' AND last_digest_slot IS NOT DISTINCT FROM $2 RETURNING 1""",
            slot, previous)
        return bool(claimed)

    async def unsynced_closed_hitl(self, limit: int = 10) -> list[Any]:
        rows = await self.connection.fetch(
            f"""{self.HITL_SELECT} WHERE h.status <> 'OPEN' AND h.telegram_msg_id IS NOT NULL
                  AND h.telegram_card_closed_at IS NULL AND h.resolved_at > now() - interval '7 days'
                ORDER BY h.resolved_at LIMIT $1""", limit)
        return [_hitl(r) for r in rows]

    async def mark_hitl_card_closed(self, hitl_id: str) -> None:
        await self.connection.execute(
            """UPDATE public.hitl_requests SET telegram_card_closed_at=now()
               WHERE id=$1::uuid AND telegram_card_closed_at IS NULL""", hitl_id)
