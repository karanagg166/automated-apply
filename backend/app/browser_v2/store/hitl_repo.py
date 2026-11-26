"""PostgresStore HITL inbox, digest-day claim and Telegram state (mixin over PostgresBase)."""

from __future__ import annotations

import json

from backend.app.browser_v2.store.base import PostgresBase, _hitl, _record, _uuid
from backend.app.browser_v2.store.records import (
    ANSWER_KINDS,
    HITL_CHANNELS,
    HITL_STATUSES,
    REF_PATTERN,
    TelegramState,
    _telegram_changes,
)


class HitlRepo(PostgresBase):
    async def create_hitl(self, record, platform, kind, prompt, context):
        return str(await self.connection.fetchval(
            """INSERT INTO public.hitl_requests (application_id, platform, kind, prompt_text, context)
               VALUES ($1::uuid, $2, $3, $4, $5::jsonb) RETURNING id""",
            record.id if record else None, platform, kind, prompt, json.dumps(context, default=str)))

    async def open_hitl_exists(self, platform, kind):
        return bool(await self.connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.hitl_requests WHERE platform=$1 AND kind=$2 AND status='OPEN')",
            platform, kind))

    async def cancel_open_hitl(self, platform, kind):
        result = await self.connection.execute(
            """UPDATE public.hitl_requests SET status='CANCELLED', resolved_at=now()
               WHERE platform=$1 AND kind=$2 AND status='OPEN'""", platform, kind)
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    async def get_hitl(self, hitl_id):
        if _uuid(hitl_id) is None:
            return None
        row = await self.connection.fetchrow(f"{self.HITL_SELECT} WHERE h.id=$1::uuid", hitl_id)
        return _hitl(row) if row else None

    async def find_open_hitl_by_ref(self, ref):
        ref = (ref or "").lower().replace("-", "")
        if not REF_PATTERN.match(ref):
            return []
        rows = await self.connection.fetch(
            f"""{self.HITL_SELECT} WHERE h.status='OPEN' AND replace(h.id::text, '-', '') LIKE $1 || '%'
                ORDER BY h.created_at LIMIT 5""", ref)
        return [_hitl(r) for r in rows]

    async def find_hitl_by_message(self, message_id):
        row = await self.connection.fetchrow(
            f"{self.HITL_SELECT} WHERE h.telegram_msg_id=$1 ORDER BY h.created_at DESC LIMIT 1", message_id)
        return _hitl(row) if row else None

    async def list_hitl(self, status="OPEN", platform=None, limit=50, offset=0):
        where = "($1::text IS NULL OR h.status=$1) AND ($2::text IS NULL OR h.platform=$2)"
        rows = await self.connection.fetch(
            f"{self.HITL_SELECT} WHERE {where} ORDER BY h.created_at, h.id LIMIT $3 OFFSET $4",
            status, platform, limit, offset)
        total = await self.connection.fetchval(
            f"SELECT count(*) FROM public.hitl_requests h WHERE {where}", status, platform)
        return [_hitl(r) for r in rows], total

    async def undelivered_hitl(self, limit=10):
        rows = await self.connection.fetch(
            f"""{self.HITL_SELECT} WHERE h.status='OPEN' AND h.telegram_msg_id IS NULL
                ORDER BY h.created_at, h.id LIMIT $1""", limit)
        return [_hitl(r) for r in rows]

    async def mark_hitl_delivered(self, hitl_id, message_id):
        await self.connection.execute(
            """UPDATE public.hitl_requests SET telegram_msg_id=$2
               WHERE id=$1::uuid AND telegram_msg_id IS NULL""", hitl_id, message_id)

    async def close_hitl(self, hitl_id, status, answer_text, via):
        if status not in HITL_STATUSES or via not in HITL_CHANNELS:
            raise ValueError("invalid hitl status or channel")
        if _uuid(hitl_id) is None:
            return None
        # Conditional on OPEN: a double-clicked button or a dashboard/Telegram race resolves once.
        closed = await self.connection.fetchval(
            """UPDATE public.hitl_requests SET status=$2, answer_text=$3, resolved_at=now(), resolved_via=$4
               WHERE id=$1::uuid AND status='OPEN' RETURNING id""", hitl_id, status, answer_text, via)
        return await self.get_hitl(str(closed)) if closed else None

    async def expire_stale_hitl(self, kind, older_than):
        """OPEN requests of `kind` created before `older_than` -> EXPIRED (conditional on OPEN)."""
        ids = await self.connection.fetch(
            """UPDATE public.hitl_requests SET status='EXPIRED', resolved_at=now(), resolved_via='worker'
               WHERE status='OPEN' AND kind=$1 AND created_at < $2 RETURNING id""", kind, older_than)
        rows = [await self.get_hitl(str(r["id"])) for r in ids]
        return [r for r in rows if r is not None]

    async def claim_digest_day(self, day):
        """Atomic once-per-local-day claim (survives restarts and two concurrent senders)."""
        await self.get_telegram_state()
        claimed = await self.connection.fetchval(
            """UPDATE public.telegram_v2_state SET last_digest_on=$1, updated_at=now()
               WHERE singleton_key='primary' AND last_digest_on IS DISTINCT FROM $1 RETURNING 1""", day)
        return bool(claimed)

    async def release_digest_day(self, day, previous):
        await self.connection.execute(
            """UPDATE public.telegram_v2_state SET last_digest_on=$2, updated_at=now()
               WHERE singleton_key='primary' AND last_digest_on=$1""", day, previous)

    async def count_open_hitl(self, platform=None):
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.hitl_requests WHERE status='OPEN' AND ($1::text IS NULL OR platform=$1)",
            platform)

    async def requeued_applications(self, platform, limit=20):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications a
                WHERE a.platform=$1 AND a.state='SCORED' AND (a.retry_after IS NULL OR a.retry_after <= now())
                  AND EXISTS (SELECT 1 FROM public.hitl_requests h WHERE h.application_id=a.id
                              AND h.status='ANSWERED' AND h.consumed_at IS NULL)
                ORDER BY a.retry_after NULLS LAST, a.updated_at LIMIT $2""", platform, limit)
        return [_record(r) for r in rows]

    async def hitl_answers(self, application_id):
        if _uuid(application_id) is None:
            return {}
        rows = await self.connection.fetch(
            """SELECT prompt_text, answer_text FROM public.hitl_requests
               WHERE application_id=$1::uuid AND status='ANSWERED' AND kind = ANY($2::text[])
                 AND answer_text IS NOT NULL ORDER BY resolved_at NULLS FIRST, created_at""",
            application_id, list(ANSWER_KINDS))
        return {r["prompt_text"]: r["answer_text"] for r in rows}

    async def mark_hitl_consumed(self, application_id):
        if _uuid(application_id) is None:
            return 0
        result = await self.connection.execute(
            """UPDATE public.hitl_requests SET consumed_at=now()
               WHERE application_id=$1::uuid AND status='ANSWERED' AND consumed_at IS NULL""",
            application_id)
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    async def get_telegram_state(self):
        row = await self.connection.fetchrow(
            """INSERT INTO public.telegram_v2_state (singleton_key) VALUES ('primary')
               ON CONFLICT (singleton_key) DO UPDATE SET singleton_key=EXCLUDED.singleton_key
               RETURNING *""")
        return TelegramState.from_row(dict(row))

    async def update_telegram_state(self, **changes):
        changes = _telegram_changes(changes)
        await self.get_telegram_state()
        columns = list(changes)
        assignments = "".join(f"{column}=${index + 1}, " for index, column in enumerate(columns))
        row = await self.connection.fetchrow(
            f"""UPDATE public.telegram_v2_state SET {assignments}updated_at=now()
                WHERE singleton_key='primary' RETURNING *""", *[changes[c] for c in columns])
        return TelegramState.from_row(dict(row))
