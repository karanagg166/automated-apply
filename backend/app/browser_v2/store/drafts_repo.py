"""PostgresStore email drafts repository (mixin over PostgresBase)."""

from __future__ import annotations

from backend.app.browser_v2.store.base import PostgresBase, _draft, _uuid
from backend.app.browser_v2.store.records import (
    BODY_PREVIEW_CHARS,
    DRAFT_CHANNELS,
    DraftReservation,
    _clip,
)


class DraftsRepo(PostgresBase):
    async def reserve_email_draft(self, application_id, platform, recipient_email):
        if _uuid(application_id) is None:
            raise ValueError("invalid application id")
        # Atomic claim: UNIQUE(application_id) means only one caller ever owns the row.
        # A definite FAILED attempt may be re-claimed; PENDING/CREATED never are.
        claimed = await self.connection.fetchval(
            """INSERT INTO public.email_drafts (application_id, platform, recipient_email, status)
               VALUES ($1::uuid, $2, $3, 'PENDING')
               ON CONFLICT (application_id) DO UPDATE
                   SET status='PENDING', recipient_email=EXCLUDED.recipient_email, last_error=NULL,
                       updated_at=now()
                   WHERE public.email_drafts.status='FAILED'
               RETURNING id""", application_id, platform, recipient_email)
        row = await self.connection.fetchrow(
            f"{self.DRAFT_SELECT} WHERE d.application_id=$1::uuid", application_id)
        return DraftReservation(claimed is not None, _draft(row) if row else None)

    async def complete_email_draft(self, draft_id, *, channel, subject, body_preview, composer,
                                   enrichment_source, external_draft_id):
        if channel not in DRAFT_CHANNELS:
            raise ValueError("invalid draft channel")
        async with self.connection.transaction():
            application_id = await self.connection.fetchval(
                """UPDATE public.email_drafts SET status='CREATED', channel=$2, subject=$3, body_preview=$4,
                       composer=$5, enrichment_source=$6, external_draft_id=$7, last_error=NULL,
                       created_at=now(), updated_at=now()
                   WHERE id=$1::uuid AND status='PENDING' RETURNING application_id""",
                draft_id, channel, subject, _clip(body_preview, BODY_PREVIEW_CHARS), composer,
                enrichment_source, external_draft_id)
            if application_id is not None:
                await self.connection.execute(
                    """UPDATE public.applications SET draft_created_at=COALESCE(draft_created_at, now()),
                           updated_at=now() WHERE id=$1""", application_id)
        row = await self.connection.fetchrow(f"{self.DRAFT_SELECT} WHERE d.id=$1::uuid", draft_id)
        return _draft(row)

    async def fail_email_draft(self, draft_id, error, *, ambiguous=False):
        await self.connection.execute(
            """UPDATE public.email_drafts SET status=$3, last_error=$2, updated_at=now()
               WHERE id=$1::uuid AND status='PENDING'""",
            draft_id, _clip(error, 200), "PENDING" if ambiguous else "FAILED")

    async def get_email_draft(self, application_id):
        if _uuid(application_id) is None:
            return None
        row = await self.connection.fetchrow(
            f"{self.DRAFT_SELECT} WHERE d.application_id=$1::uuid", application_id)
        return _draft(row) if row else None

    async def list_email_drafts(self, platform=None, limit=50, offset=0):
        rows = await self.connection.fetch(
            f"""{self.DRAFT_SELECT} WHERE ($1::text IS NULL OR d.platform=$1)
                ORDER BY d.created_at DESC, d.id LIMIT $2 OFFSET $3""", platform, limit, offset)
        total = await self.connection.fetchval(
            "SELECT count(*) FROM public.email_drafts d WHERE ($1::text IS NULL OR d.platform=$1)", platform)
        return [_draft(r) for r in rows], total

    async def count_email_drafts(self, status="CREATED", platform=None, since=None):
        return await self.connection.fetchval(
            """SELECT count(*) FROM public.email_drafts WHERE status=$1
                   AND ($2::text IS NULL OR platform=$2) AND ($3::timestamptz IS NULL OR created_at >= $3)""",
            status, platform, since)
