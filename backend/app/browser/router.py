"""Authenticated local orchestration. Owner bearer and dashboard CSRF remain mandatory."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.applications import ProtectedApplicationRoute
from backend.app.browser.contracts import BrowserAction, OpenBrowser, PrepareBrowser
from backend.app.browser.navigation import ResumePage
from backend.app.browser.opportunity import ReviewOpportunity
from backend.app.browser.owner_approval import require_owner_approval
from backend.app.browser.runner import browser
from backend.app.browser.service import analyze, fill, prepare, status
from backend.app.browser.steps import AdvanceStep
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.schemas.applications import RevisionInput
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


@router.post("/{packet_id}/page-preview")
async def preview_current_page(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.navigation import preview

    async with browser.operations.run(
        packet_id, "page_preview", data.expected_revision
    ):
        try:
            async with asyncio.timeout(15):
                return await preview(session, packet_id, data.expected_revision)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                409, "Page review interrupted; inspect the browser manually"
            ) from None


@router.post("/{packet_id}/resume-page", dependencies=[Depends(require_owner_approval)])
async def resume_current_page(
    packet_id: UUID, data: ResumePage, session: AsyncSession = Depends(get_db_session)
):
    from backend.app.browser.navigation import resume

    async with browser.operations.run(packet_id, "resume_page", data.expected_revision):
        try:
            async with asyncio.timeout(45):
                return await resume(session, packet_id, data)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                409,
                "Page resumption interrupted; inspect saved status before continuing",
            ) from None


@router.post("/{packet_id}/step-preview")
async def preview_step(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.steps import preview

    async with browser.operations.run(
        packet_id, "step_preview", data.expected_revision
    ):
        try:
            async with asyncio.timeout(15):
                return await preview(session, packet_id, data.expected_revision)
        except TimeoutError:
            raise HTTPException(
                409, "Step review timed out; take over manually"
            ) from None


@router.post(
    "/{packet_id}/advance-step", dependencies=[Depends(require_owner_approval)]
)
async def advance_application_step(
    packet_id: UUID, data: AdvanceStep, session: AsyncSession = Depends(get_db_session)
):
    from backend.app.browser.steps import advance

    async with browser.operations.run(
        packet_id, "advance_step", data.expected_revision
    ):
        try:
            async with asyncio.timeout(35):
                return await advance(session, packet_id, data)
        except TimeoutError:
            raise HTTPException(
                409, "Step interrupted; inspect operation status and take over manually"
            ) from None


@router.post("/{packet_id}/opportunity-preview")
async def preview_opportunity(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.opportunity import capture

    async with browser.operations.run(
        packet_id, "opportunity_preview", data.expected_revision
    ):
        try:
            async with asyncio.timeout(15):
                return await capture(session, packet_id, data.expected_revision)
        except TimeoutError:
            raise HTTPException(
                409, "Context capture timed out; take over manually"
            ) from None


@router.post(
    "/{packet_id}/opportunity-approve", dependencies=[Depends(require_owner_approval)]
)
async def approve_opportunity(
    packet_id: UUID,
    data: ReviewOpportunity,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.opportunity import approve

    async with browser.operations.run(
        packet_id, "opportunity_approve", data.expected_revision
    ):
        try:
            async with asyncio.timeout(20):
                return await approve(session, packet_id, data)
        except TimeoutError:
            raise HTTPException(
                409, "Context approval timed out; check saved state before retrying"
            ) from None


@router.post("")
async def prepare_application(
    data: PrepareBrowser, session: AsyncSession = Depends(get_db_session)
):
    result = await prepare(session, data)
    await session.commit()
    return result


@router.get("/{packet_id}")
async def get_application_status(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await status(session, packet_id)


@router.get("/{packet_id}/operation")
async def get_browser_operation(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    packet = await ApplicationPacketService(session).repo.get(packet_id)
    return {
        "packet_revision": packet.revision,
        "active_operation": browser.operations.public(packet_id),
        "cancellation_pending": str(packet_id) in browser.operations.stopping,
    }


@router.post("/{packet_id}/open")
async def open_application(
    packet_id: UUID, data: OpenBrowser, session: AsyncSession = Depends(get_db_session)
):
    if not data.approve_dedicated_profile or not data.confirm_destination_permission:
        raise HTTPException(
            422,
            "Explicit dedicated-profile and destination permission approval required",
        )
    async with browser.operations.run(packet_id, "open", data.expected_revision):
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
    # This assisted action never authorizes submission; the mock dispatch has separate gates.
    if data.action == "submit":
        raise HTTPException(
            403,
            "Automated submission is not enabled for any destination; submit manually after review",
        )
    if data.action == "cancel":
        from backend.app.browser.cancellation import cancel

        return await cancel(session, packet_id, data)
    async with browser.operations.run(packet_id, data.action, data.expected_revision):
        service = ApplicationPacketService(session)
        if data.action == "preview":
            return await status(session, packet_id)
        packet, _, _ = await service.locked(packet_id, data.expected_revision)
        runtime = browser.sessions.get(str(packet_id))
        if runtime is None or runtime.page.is_closed():
            raise HTTPException(
                409,
                "Browser disconnected; reopen and analyze. Nothing will be replayed",
            )
        if data.action == "take_over":
            runtime.paused_for_resume = False
            await runtime.set_manual(True)
            return await status(session, packet_id)
        if (
            runtime.paused_for_resume
            or runtime.page.url != runtime.url
            or runtime.document_epoch != runtime.assisted_document_epoch
        ):
            raise HTTPException(
                409,
                "The page changed; preview and authorize the current page to resume assistance",
            )
        if runtime.manual:
            if data.action != "analyze":
                raise HTTPException(
                    409, "Owner controls the browser; analyze to resume assistance"
                )
            await runtime.set_manual(False)
            runtime.blocked_step_requests = 0
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

    async with browser.operations.run(
        packet_id, "submission_preview", data.expected_revision
    ):
        return await preview(
            session,
            packet_id,
            data.expected_revision,
            confirm_context=data.confirm_page_context,
        )


@router.post(
    "/{packet_id}/authorize-submission", dependencies=[Depends(require_owner_approval)]
)
async def authorize_submission(
    packet_id: UUID,
    data: SubmissionAuthorization,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import authorize

    async with browser.operations.run(
        packet_id, "authorize_submission", data.expected_revision
    ):
        result = await authorize(session, packet_id, data)
        await session.commit()
        return result


@router.post("/{packet_id}/submit")
async def submit_approved_application(
    packet_id: UUID,
    data: SubmitApproved,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import submit

    async with browser.operations.run(packet_id, "submit", data.expected_revision):
        return await submit(session, packet_id, data)


@router.post("/{packet_id}/recover-submission")
async def recover_submission(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    from backend.app.browser.submissions import recover

    async with browser.operations.run(packet_id, "recover_submission"):
        return await recover(session, packet_id)


from backend.app.browser.submission_contracts import ConsentAction


@router.post("/{packet_id}/consent", dependencies=[Depends(require_owner_approval)])
async def owner_consent(
    packet_id: UUID,
    data: ConsentAction,
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.browser.submissions import set_consent

    async with browser.operations.run(packet_id, "consent", data.expected_revision):
        return await set_consent(session, packet_id, data)
