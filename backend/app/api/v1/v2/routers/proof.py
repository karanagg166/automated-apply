"""Application proof receipts: timing, form Q&A audit, linked mail and owner reconciliation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.api.v1.v2.deps import StoreDep
from backend.app.api.v1.v2.routers.applications import _application_id_or_404
from backend.app.api.v1.v2.routers.proof_views import build_proof
from backend.app.browser_v2.schemas import ApplicationRead
from backend.app.browser_v2.schemas.proof import ApplicationProof, ReconcileInput
from backend.app.browser_v2.state import (
    OWNER_RELEASE_REASON,
    ApplicationState,
    InvalidTransition,
)

router = APIRouter()
logger = logging.getLogger(__name__)
OWNER_CONFIRM_REASON = "owner_verified_applied"
RELEASE_WORD = "RELEASE"


async def _mail_events(store: Any, application_id: str) -> list[Any]:
    from backend.app.mail_v2.event_store import MailEventStore

    try:
        return await MailEventStore(getattr(store, "connection", None)).for_application(application_id)
    except Exception as exc:  # noqa: BLE001 - the receipt still renders without linked mail
        logger.info("proof mail events unavailable: %s", type(exc).__name__)
        return []


@router.get("/applications/{application_id}/proof", response_model=ApplicationProof)
async def application_proof(application_id: str, store: StoreDep) -> ApplicationProof:
    """Full proof receipt: posted -> discovered -> queued -> submitted timing, every form answer with
    its tier badge, resume variant, screenshot file name, linked mails and any outreach draft."""
    _application_id_or_404(application_id)
    record = await store.get_application(application_id)
    if record is None:
        raise HTTPException(404, "Application not found")
    events = await store.application_events(application_id) or []
    try:
        draft = await store.get_email_draft(application_id)
    except Exception:  # noqa: BLE001
        draft = None
    return build_proof(record, events, now=datetime.now(UTC), mail_events=await _mail_events(store, application_id),
                       draft=draft)


@router.post("/applications/{application_id}/reconcile", response_model=ApplicationRead)
async def reconcile_application(application_id: str, data: ReconcileInput, store: StoreDep) -> ApplicationRead:
    """Owner reconciliation of a SUBMISSION_UNKNOWN row.

    confirm_applied: the owner saw it in the portal -> APPLIED (`owner_verified_applied`).
    release_not_submitted (confirm="RELEASE"): the owner verified it was NOT delivered -> FAILED
    (`owner_verified_not_submitted`): the daily-quota slot is released and the job may be applied again.
    """
    _application_id_or_404(application_id)
    record = await store.get_application(application_id)
    if record is None:
        raise HTTPException(404, "Application not found")
    if record.state != ApplicationState.SUBMISSION_UNKNOWN:
        raise HTTPException(409, f"Only SUBMISSION_UNKNOWN rows can be reconciled (state is {record.state.value})")
    try:
        if data.action == "confirm_applied":
            receipt = dict(record.receipt or {}) | {"source": "owner_verified",
                                                    "verified_at": datetime.now(UTC).isoformat()}
            updated = await store.transition(record, ApplicationState.APPLIED, OWNER_CONFIRM_REASON,
                                             receipt=receipt, payload={"via": "dashboard"})
        else:
            if data.confirm != RELEASE_WORD:
                raise HTTPException(422, 'Type "RELEASE" to confirm the application was not submitted')
            updated = await store.transition(record, ApplicationState.FAILED, OWNER_RELEASE_REASON,
                                             payload={"via": "dashboard"})
    except InvalidTransition as exc:
        raise HTTPException(409, f"Application changed concurrently ({exc}); reload and retry") from None
    return ApplicationRead(**updated.public())
