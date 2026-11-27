"""PostgresStore applications + state-machine repository (mixin over PostgresBase)."""

from __future__ import annotations

import json
from datetime import datetime

from backend.app.browser_v2.state import (
    ApplicationState,
    InvalidTransition,
    check_transition,
)
from backend.app.browser_v2.store.base import PostgresBase, _json, _record, _uuid
from backend.app.browser_v2.store.discovery_repo import QUEUE_ORDER
from backend.app.browser_v2.store.records import ApplicationRecord, like_pattern


class ApplicationsRepo(PostgresBase):
    # --- applications ---------------------------------------------------------------
    async def get(self, platform: str, external_job_id: str) -> ApplicationRecord | None:
        row = await self.connection.fetchrow(
            f"SELECT {self.COLUMNS} FROM public.applications WHERE platform=$1 AND external_job_id=$2",
            platform, external_job_id)
        return _record(row) if row else None

    async def get_application(self, application_id):
        if _uuid(application_id) is None:
            return None
        row = await self.connection.fetchrow(
            f"SELECT {self.COLUMNS} FROM public.applications WHERE id=$1::uuid", application_id)
        return _record(row) if row else None

    async def transition(self, record, target, reason, *, receipt=None, payload=None,
                         count_attempt=False, retry_after=None):
        check_transition(record.state, target)
        async with self.connection.transaction():
            row = await self.connection.fetchrow(
                f"""UPDATE public.applications
                    SET state=$1, reason=$2, receipt=COALESCE($3::jsonb, receipt),
                        attempts=attempts + $4, version=version + 1, updated_at=now(),
                        applied_at=CASE WHEN $1='APPLIED' THEN now() ELSE applied_at END,
                        retry_after=COALESCE($7::timestamptz, retry_after)
                    WHERE id=$5::uuid AND version=$6
                    RETURNING {self.COLUMNS}""",
                ApplicationState(target).value, reason,
                json.dumps(receipt, default=str) if receipt is not None else None,
                int(count_attempt), record.id, record.version, retry_after)
            if row is None:
                raise InvalidTransition("stale_version")
            await self.connection.execute(
                """INSERT INTO public.application_state_events
                       (application_id, from_state, to_state, event_type, payload)
                   VALUES ($1::uuid, $2, $3, $4, $5::jsonb)""",
                record.id, record.state.value, ApplicationState(target).value, reason[:80],
                json.dumps((payload or {}) | {"reason": reason}, default=str))
        return _record(row)

    async def find_duplicates(self, key, *, platform, external_job_id):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE dedup_key=$1 AND NOT (platform=$2 AND external_job_id=$3)
                ORDER BY updated_at DESC LIMIT 20""", key, platform, external_job_id)
        return [_record(r) for r in rows]

    async def list_by_state(self, platform, states, limit=50):
        # Phase 9B: tier first, newest posting next, then oldest-touched (fair within a tier).
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE platform=$1 AND state = ANY($2::text[])
                  AND (retry_after IS NULL OR retry_after <= now())
                ORDER BY {QUEUE_ORDER} LIMIT $3""",
            platform, [ApplicationState(s).value for s in states], limit)
        return [_record(r) for r in rows]

    async def count_state(self, state, platform=None):
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.applications WHERE state=$1 AND ($2::text IS NULL OR platform=$2)",
            ApplicationState(state).value, platform)

    async def applied_since(self, platform: str, since: datetime) -> int:
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.applications WHERE platform=$1 AND applied_at >= $2",
            platform, since)

    async def ambiguous_submits_since(self, platform: str, since: datetime) -> int:
        """Submits with an ambiguous outcome since `since` (-> SUBMISSION_UNKNOWN, not reconciled to
        APPLIED): each may really have been sent, so the daily/hourly caps must count them."""
        return await self.connection.fetchval(
            """SELECT count(DISTINCT e.application_id) FROM public.application_state_events e
               JOIN public.applications a ON a.id = e.application_id
               WHERE a.platform=$1 AND e.to_state='SUBMISSION_UNKNOWN' AND a.state <> 'APPLIED'
                 AND e.created_at >= $2""",
            platform, since)

    async def stale_applying(self, older_than: datetime, limit: int = 20) -> list[ApplicationRecord]:
        """APPLYING rows untouched since `older_than`: a crash/kill between reserve and outcome."""
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE state='APPLYING' AND updated_at < $1 ORDER BY updated_at LIMIT $2""",
            older_than, limit)
        return [_record(r) for r in rows]

    async def list_applications(self, query):
        where = r"""($1::text IS NULL OR platform=$1) AND ($2::text IS NULL OR state=$2)
                   AND ($3::timestamptz IS NULL OR updated_at >= $3)
                   AND ($4::timestamptz IS NULL OR updated_at < $4)
                   AND ($5::text IS NULL OR company_name ILIKE $5 ESCAPE '\'
                        OR role_title ILIKE $5 ESCAPE '\')"""
        params = (query.platform, query.state, query.since, query.until,
                  like_pattern(query.q) if query.q else None)
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications WHERE {where}
                ORDER BY updated_at DESC, id LIMIT $6 OFFSET $7""",
            *params, query.limit, query.offset)
        total = await self.connection.fetchval(
            f"SELECT count(*) FROM public.applications WHERE {where}", *params)
        return [_record(r) for r in rows], total

    async def application_events(self, application_id):
        exists = await self.connection.fetchval(
            "SELECT 1 FROM public.applications WHERE id=$1::uuid", application_id)
        if not exists:
            return None
        rows = await self.connection.fetch(
            """SELECT from_state, to_state, event_type, payload::text AS payload, created_at
               FROM public.application_state_events WHERE application_id=$1::uuid
               ORDER BY created_at, id""", application_id)
        return [dict(r) | {"payload": _json(r["payload"])} for r in rows]

    # --- Phase 5: quota-hit drafts + next-day retry --------------------------------------
    async def due_retries(self, platform, now, limit=20):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE platform=$1 AND state='DRAFTED_AND_QUEUED' AND retry_after IS NOT NULL
                  AND retry_after <= $2
                ORDER BY retry_after, updated_at LIMIT $3""", platform, now, limit)
        return [_record(r) for r in rows]

    async def parked_since(self, platform, since):
        return await self.connection.fetchval(
            """SELECT count(*) FROM public.application_state_events e
               JOIN public.applications a ON a.id = e.application_id
               WHERE a.platform=$1 AND e.to_state='QUOTA_HIT_PENDING'
                 AND e.from_state IS DISTINCT FROM 'QUOTA_HIT_PENDING' AND e.created_at >= $2""",
            platform, since)
