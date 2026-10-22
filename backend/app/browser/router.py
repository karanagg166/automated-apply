"""Authenticated local orchestration. Owner bearer and dashboard CSRF remain mandatory."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.applications import ProtectedApplicationRoute
from backend.app.browser.contracts import BrowserAction, OpenBrowser, PrepareBrowser
from backend.app.browser.owner_approval import require_owner_approval
from backend.app.browser.runner import browser
from backend.app.browser.service import analyze, fill, metadata, prepare, status
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.services.applications.service import ApplicationPacketService


async def local_boundary(request: Request):
    settings = get_settings()
    if not settings.BROWSER_ASSISTANT_ENABLED:
        raise HTTPException(503, "Local browser assistant is disabled")
    if not request.client or request.client.host not in {
        "127.0.0.1",
        "::1",
        "testclient",
    }:
        raise HTTPException(403, "Browser operations require a loopback connection")
    if request.headers.get("origin"):
        raise HTTPException(403, "Use the authenticated dashboard gateway or local CLI")


router = APIRouter(
    prefix="/api/v1/browser-applications",
    tags=["Local browser assistance"],
    route_class=ProtectedApplicationRoute,
    dependencies=[Depends(require_api_token), Depends(local_boundary)],
)


@router.post("")
async def prepare_application(
    data: PrepareBrowser, session: AsyncSession = Depends(get_db_session)
):
    return await prepare(session, data)


@router.get("/{packet_id}")
async def get_application_status(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await status(session, packet_id)


@router.post("/{packet_id}/open")
async def open_application(
    packet_id: UUID, data: OpenBrowser, session: AsyncSession = Depends(get_db_session)
):
    if not data.approve_dedicated_profile or not data.confirm_destination_permission:
        raise HTTPException(
            422,
            "Explicit dedicated-profile and destination permission approval required",
        )
    async with browser.lock(packet_id):
        service = ApplicationPacketService(session)
        packet, _, _ = await service.locked(packet_id, data.expected_revision)
        if not packet.application_url:
            raise HTTPException(409, "No saved employer application URL")
        try:
            await browser.open(packet_id, packet.application_url, get_settings())
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                409, "Browser launch or navigation failed; no submission attempted"
            ) from None
        return await status(session, packet_id)


@router.post("/{packet_id}/actions")
async def application_action(
    packet_id: UUID,
    data: BrowserAction,
    session: AsyncSession = Depends(get_db_session),
):
    # Fail closed independently of current state or caller. No adapter authorizes submissions yet.
    if data.action == "submit":
        raise HTTPException(
            403,
            "Automated submission is not enabled for any destination; submit manually after review",
        )
    async with browser.lock(packet_id):
        service = ApplicationPacketService(session)
        if data.action == "preview":
            return await status(session, packet_id)
        if data.action == "cancel":
            packet = await service.repo.get(packet_id, lock=True)
            if packet.revision != data.expected_revision:
                raise HTTPException(
                    409, "Packet revision changed; reload before cancelling"
                )
            from backend.app.browser.adapters import execution_adapter

            if execution_adapter(
                packet.application_url, get_settings()
            ).submission_enabled:
                from backend.app.browser.submissions import attempt_for, finish, revoke

                await revoke(session, packet_id)
                attempt = await attempt_for(session, packet_id)
                if attempt and attempt.state != "verified":
                    await finish(
                        session,
                        attempt.id,
                        None,
                        diagnostic="owner_cancelled_after_dispatch_outcome_unknown",
                    )
            await browser.close(packet_id)
            saved = await metadata(session, packet_id)
            if saved:
                saved.value = {**saved.value, "diagnostic": "cancelled"}
            return await status(session, packet_id)
        packet, _, _ = await service.locked(packet_id, data.expected_revision)
        runtime = browser.sessions.get(str(packet_id))
        if runtime is None or runtime.page.is_closed():
            raise HTTPException(
                409,
                "Browser disconnected; reopen and analyze. Nothing will be replayed",
            )
        if data.action == "take_over":
            runtime.manual = True
            await runtime.page.evaluate("window.__aaManual = true")
            return await status(session, packet_id)
        if runtime.manual:
            if data.action != "analyze":
                raise HTTPException(
                    409, "Owner controls the browser; analyze to resume assistance"
                )
            runtime.manual = False
            await runtime.page.evaluate("window.__aaManual = false")
        try:
            async with asyncio.timeout(45):
                if data.action == "analyze":
                    return await analyze(session, packet, service, runtime)
                return await fill(
                    session,
                    packet,
                    service,
                    runtime,
                    data.confirm_reviewed_values,
                    data.confirm_page_context,
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                409, "Browser operation interrupted; inspect the page and reanalyze"
            ) from None


from backend.app.browser.submission_contracts import (
    SubmissionAuthorization,
    SubmissionPreviewRequest,
    SubmitApproved,
)


@router.post("/{packet_id}/submission-preview")
async def submission_preview(
    packet_id: UUID,
    data: SubmissionPreviewRequest,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import preview

    async with browser.lock(packet_id):
        return await preview(
            session,
            packet_id,
            data.expected_revision,
            confirm_context=data.confirm_page_context,
        )


@router.post("/{packet_id}/authorize-submission", dependencies=[Depends(require_owner_approval)])
async def authorize_submission(
    packet_id: UUID,
    data: SubmissionAuthorization,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import authorize

    async with browser.lock(packet_id):
        return await authorize(session, packet_id, data)


@router.post("/{packet_id}/submit")
async def submit_approved_application(
    packet_id: UUID,
    data: SubmitApproved,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import submit

    async with browser.lock(packet_id):
        return await submit(session, packet_id, data)


@router.post("/{packet_id}/recover-submission")
async def recover_submission(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    from backend.app.browser.submissions import recover

    async with browser.lock(packet_id):
        return await recover(session, packet_id)


from backend.app.browser.submission_contracts import ConsentAction


@router.post("/{packet_id}/consent", dependencies=[Depends(require_owner_approval)])
async def owner_consent(
    packet_id: UUID,
    data: ConsentAction,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import set_consent

    async with browser.lock(packet_id):
        return await set_consent(session, packet_id, data)
