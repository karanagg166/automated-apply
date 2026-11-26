"""Deduplicated store of read-only mail events (public.mail_events or memory)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from backend.app.mail_v2.read_models import MailEvent


# --- service ------------------------------------------------------------------------------------
class MailEventStore:
    """public.mail_events (Postgres) or memory; dedup on message_key."""

    def __init__(self, connection: Any = None) -> None:
        self.connection = connection
        self.memory: dict[str, MailEvent] = {}

    async def add(self, event: MailEvent) -> bool:
        """True when new (first time this message is seen)."""
        if self.connection is None:
            if event.message_key in self.memory:
                return False
            event.created_at = datetime.now(UTC)
            event.id = hashlib.sha256(event.message_key.encode()).hexdigest()[:32]
            self.memory[event.message_key] = event
            return True
        row = await self.connection.fetchrow(
            """INSERT INTO public.mail_events (message_key, kind, source, platform, company_name, sender, subject,
                   snippet, application_id, received_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid, $10)
               ON CONFLICT (message_key) DO NOTHING RETURNING id""",
            event.message_key, event.kind, event.source, event.platform, (event.company_name or None) and
            event.company_name[:200], (event.sender or None) and event.sender[:200],
            (event.subject or None) and event.subject[:300], (event.snippet or None) and event.snippet[:500],
            event.application_id, event.received_at)
        if row is not None:
            event.id = str(row["id"])
        return row is not None

    async def mark_alerted(self, message_key: str) -> None:
        if self.connection is None:
            if message_key in self.memory:
                self.memory[message_key].alerted_at = datetime.now(UTC)
            return
        await self.connection.execute("UPDATE public.mail_events SET alerted_at=now() WHERE message_key=$1",
                                      message_key)

    async def recent(self, kinds: Iterable[str] | None = None, limit: int = 50) -> list[MailEvent]:
        wanted = list(kinds) if kinds else ["RECRUITER_REPLY", "INTERVIEW", "JOB_ALERT"]
        if self.connection is None:
            rows = [e for e in self.memory.values() if e.kind in wanted]
            rows.sort(key=lambda e: e.created_at or datetime.now(UTC), reverse=True)
            return rows[:limit]
        rows = await self.connection.fetch(
            """SELECT id, message_key, kind, source, platform, company_name, sender, subject, snippet,
                      application_id, received_at, alerted_at, created_at
               FROM public.mail_events WHERE kind = ANY($1::text[]) ORDER BY created_at DESC LIMIT $2""",
            wanted, limit)
        return [MailEvent(**{**dict(r), "id": str(r["id"]),
                             "application_id": str(r["application_id"]) if r["application_id"] else None})
                for r in rows]

    @staticmethod
    async def ready(connection: Any) -> bool:
        try:
            return bool(await connection.fetchval("SELECT to_regclass('public.mail_events') IS NOT NULL"))
        except Exception:  # noqa: BLE001
            return False
