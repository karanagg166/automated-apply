"""v2 control plane, Phase 5 quota fallback (Gmail drafts + enrichment; READ + DRAFT ONLY) and the
Phase 6A READ-ONLY recruiter replies.

``replies_router`` is separate from ``router`` only so the composer can keep the original route
registration order (``/mail/replies`` was registered after the Phase 6A agent routes).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.app.api.v1.v2.deps import (
    PLATFORM_PATTERN,
    AIDep,
    EnrichmentDep,
    MailDep,
    StoreDep,
    mail_config,
)
from backend.app.browser_v2.schemas import (
    DraftNowRead,
    EmailDraftPage,
    EmailDraftRead,
    EnrichmentStatusRead,
    MailEventRead,
    MailReplyPage,
    MailStatusRead,
)
from backend.app.browser_v2.state import ApplicationState

router = APIRouter()
replies_router = APIRouter()

# --- Phase 5: quota fallback (Gmail drafts + enrichment). READ + DRAFT ONLY. -------------
DRAFT_NOW_CODES = {
    "quota_hit_drafted_and_queued": ("drafted", "Gmail draft created — review it in Gmail Drafts before sending."),
    "quota_hit_queued_already_drafted": ("already_drafted", "A Gmail draft already exists for this job."),
    "quota_hit_queued_no_email": ("no_email_found",
                                  "No recruiter email found (JD, careers page and free-tier lookups); no draft made."),
    "quota_hit_queued_draft_failed": ("draft_failed", "The draft could not be saved; see the error."),
    "quota_hit_queued_draft_unavailable": ("mail_unconfigured", (
        "Mail bridge not configured: set GMAIL_IMAP_EMAIL + GMAIL_IMAP_APP_PASSWORD or enable Mail.app.")),
}


@router.get("/drafts", response_model=EmailDraftPage)
async def list_email_drafts(
    store: StoreDep,
    platform: Annotated[str | None, Query(max_length=40, pattern=PLATFORM_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> EmailDraftPage:
    """Gmail drafts created by the quota fallback (newest first) with each job's retry status."""
    rows, total = await store.list_email_drafts(platform, limit, offset)
    return EmailDraftPage(items=[EmailDraftRead.model_validate(row.public()) for row in rows], total=total,
                          limit=limit, offset=offset)


@router.get("/enrichment/status", response_model=EnrichmentStatusRead)
async def enrichment_status(enrichment: EnrichmentDep) -> EnrichmentStatusRead:
    """Apollo / Apify / SignalHire config state, today's credits vs free cap, cached domains. No keys."""
    return EnrichmentStatusRead.model_validate(await enrichment.status())


@router.get("/mail/status", response_model=MailStatusRead)
async def mail_status(mail: MailDep) -> MailStatusRead:
    """IMAP / Mail.app draft bridge config (no network, no Automation prompt). Never returns secrets."""
    return MailStatusRead.model_validate(mail.status())


@router.post("/applications/{application_id}/draft-now", response_model=DraftNowRead,
             responses={404: {"description": "Application not found"},
                        409: {"description": "Application is mid-submission (APPLYING)"},
                        503: {"description": "Mail bridge not configured"}})
async def draft_now(application_id: str, store: StoreDep, ai: AIDep, mail: MailDep,
                    enrichment: EnrichmentDep) -> DraftNowRead:
    """Enrichment + exactly one Gmail draft for this job (idempotent; never changes its state)."""
    from uuid import UUID

    from backend.app.browser_v2.quota import QuotaHitProcessor
    from backend.app.mail_v2.composer import DraftComposer

    try:
        UUID(application_id)
    except ValueError:
        if not application_id.startswith("mem-"):
            raise HTTPException(404, "Application not found") from None
    record = await store.get_application(application_id)
    if record is None:
        raise HTTPException(404, "Application not found")
    if record.state is ApplicationState.APPLYING:
        raise HTTPException(409, "Application is mid-submission; try again after it settles")
    if not mail.enabled and not await mail.already_drafted(record):
        raise HTTPException(503, DRAFT_NOW_CODES["quota_hit_queued_draft_unavailable"][1])
    processor = QuotaHitProcessor(store, enrichment=enrichment, mail=mail, composer=DraftComposer(ai.router), ai=ai)
    profile, _ = await store.load_profile()
    if profile:
        ai.bind_profile(profile)
    reason, payload = await processor.draft_once(record, profile)
    code, message = DRAFT_NOW_CODES.get(reason, ("draft_failed", "The draft could not be saved."))
    draft = await store.get_email_draft(record.id)
    enrichment = payload.get("enrichment") or {}
    if code == "draft_failed" and payload.get("draft_reason"):
        message = f"{message} ({payload['draft_reason']})"
    return DraftNowRead.model_validate({
        "ok": code in ("drafted", "already_drafted"), "code": code, "message": message,
        "channel": draft.channel if draft is not None else None,
        "enrichment_status": enrichment.get("status"), "enrichment_source": enrichment.get("source"),
        "draft": draft.public() if draft is not None else None})


@replies_router.get("/mail/replies", response_model=MailReplyPage)
async def mail_replies(store: StoreDep, limit: Annotated[int, Query(ge=1, le=100)] = 30) -> MailReplyPage:
    """Recruiter replies / interview alerts found by the READ-ONLY inbox watcher (newest first)."""
    from backend.app.mail_v2.reader import MailEventStore, MailReadService

    connection = getattr(store, "connection", None)
    ready = connection is not None and await MailEventStore.ready(connection)
    rows = await MailEventStore(connection).recent(("RECRUITER_REPLY", "INTERVIEW"), limit=limit) if ready else []
    reader = MailReadService(mail_config())
    return MailReplyPage(configured=reader.any_configured, tiers=reader.status()["tiers"],
                         items=[MailEventRead(**row.public()) for row in rows])
