"""Integrated owner-reviewed browser workflows with separate route and approval boundaries."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.router import owner_ui
from backend.app.api.v1.applications import ProtectedApplicationRoute
from backend.app.browser.company_source import ReadCompanySource
from backend.app.browser.contracts import (
    BrowserAction,
    FillPlan,
    OpenBrowser,
    PrepareBrowser,
    Review,
)
from backend.app.browser.extension_tasks import ExtensionTask, TaskControl
from backend.app.browser.navigation import ResumePage
from backend.app.browser.opportunity import ReviewOpportunity
from backend.app.browser.owner_approval import require_owner_approval
from backend.app.browser.runner import browser
from backend.app.browser.service import FormService, analyze, fill, prepare, status
from backend.app.browser.steps import AdvanceStep
from backend.app.browser.submission_contracts import (
    ConsentAction,
    Submission,
    SubmissionApproval,
    SubmissionAuthorization,
    SubmissionPreviewRequest,
    SubmitApproved,
)
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.models import OwnerPreference
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.schemas.applications import RevisionInput
from backend.app.services.applications.service import ApplicationPacketService

router = APIRouter(
    prefix="/api/v1/browser", tags=["Browser forms"], route_class=OwnerRoute
)


@router.get("/extension-tasks", response_model=list[ExtensionTask])
async def extension_tasks(session: AsyncSession = Depends(get_db_session, scope="function")):
    from backend.app.browser.extension_tasks import rows
    return [row.value for row in await rows(session)]


@router.get("/extension-tasks/application/{application_id}", response_model=ExtensionTask | None)
async def extension_task(application_id: UUID, session: AsyncSession = Depends(get_db_session, scope="function")):
    from backend.app.browser.extension_tasks import by_application
    return await by_application(session, application_id)


@router.post("/extension-tasks/{task_id}/control", response_model=ExtensionTask)
async def control_extension_task(task_id: UUID, data: TaskControl, request: Request,
                                 session: AsyncSession = Depends(get_db_session, scope="function")):
    from backend.app.browser.extension_tasks import control, load
    from backend.app.execution.store import memory_row
    owner_ui(request)
    try:
        await memory_row(session, lock=True)
        return await control(session, get_settings(), await load(session, task_id), data.action, data.expected_version)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/plans", response_model=list[FillPlan])
async def plans(session: AsyncSession = Depends(get_db_session, scope="function")):
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(OwnerPreference.key.like("fill_plan:%"))
            .order_by(OwnerPreference.created_at.desc())
            .limit(20)
        )
    ).all()
    return [FillPlan.model_validate(r.value) for r in rows]


@router.post("/plans/{plan_id}/review", response_model=FillPlan)
async def review(
    plan_id: UUID,
    data: Review,
    request: Request,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    owner_ui(request)
    try:
        return await FormService(session, get_settings()).review(
            plan_id, data.field_ids
        )
    except ValueError:
        raise HTTPException(409, "fill_plan_stale_or_review_rejected") from None


@router.post("/stop")
async def stop(request: Request, session: AsyncSession = Depends(get_db_session, scope="function")):
    from backend.app.browser.queue import stop_all

    owner_ui(request)
    await stop_all(session)
    from backend.app.browser import extension_tasks
    from backend.app.execution.store import memory_row
    await memory_row(session, lock=True)
    for task in await extension_tasks.rows(session):
        if task.value["state"] not in extension_tasks.TERMINAL:
            extension_tasks.move(session, task, "PAUSED", "global_stop",
                plan_id=None, authorization_id=None, browser_connection="paused")
    return {"status": "cancelled", "submitted": False}


@router.post("/plans/{plan_id}/next")
async def next_step(
    plan_id: UUID, request: Request, session: AsyncSession = Depends(get_db_session, scope="function")
):
    from datetime import datetime, timezone

    owner_ui(request)
    service = FormService(session, get_settings())
    try:
        _, plan = await service.load(plan_id)
        await service.fresh(plan)
        if (
            plan.mode != "local_automation"
            or plan.state != "finished"
            or not plan.inspection.has_next
        ):
            raise ValueError("invalid_next")
        rows = (
            await session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.like("browser_job:%"))
                .with_for_update()
            )
        ).all()
        job = next((r for r in rows if r.value.get("plan_id") == str(plan_id)), None)
        if (
            not job
            or job.value["state"] != "form_filled"
            or job.value.get("step_count", 1) >= 5
            or datetime.fromisoformat(job.value["expires_at"])
            <= datetime.now(timezone.utc)
        ):
            raise ValueError("invalid_next")
        job.value = {
            **job.value,
            "state": "queued",
            "next_requested": True,
            "step_count": job.value.get("step_count", 1) + 1,
        }
        return {"status": "pending_browser", "submitted": False}
    except ValueError:
        raise HTTPException(409, "next_step_requires_current_completed_form") from None


@router.get("/submissions", response_model=list[Submission])
async def submissions(session: AsyncSession = Depends(get_db_session, scope="function")):
    from backend.app.browser.submission import SubmissionService

    return [
        r.value for r in (await SubmissionService(session, get_settings()).rows())[:50]
    ]


@router.post("/submissions/{application_id}/approve", response_model=Submission)
async def approve_submission(
    application_id: UUID,
    data: SubmissionApproval,
    request: Request,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.agent.router import OWNER
    from backend.app.browser.submission import SubmissionService

    owner_ui(request)
    try:
        return await SubmissionService(session, get_settings()).approve(
            application_id, OWNER, data
        )
    except ValueError:
        raise HTTPException(409, "exact_current_submission_review_required") from None


@router.post("/submissions/{application_id}/execute", response_model=Submission)
async def execute_submission(
    application_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.agent.router import OWNER
    from backend.app.browser.submission import SubmissionService

    owner_ui(request)
    try:
        return await SubmissionService(session, get_settings()).release(
            application_id, OWNER
        )
    except ValueError:
        raise HTTPException(409, "backend_authorized_submission_required") from None


@router.post("/submissions/stop")
async def stop_submissions(
    request: Request, session: AsyncSession = Depends(get_db_session, scope="function")
):
    from backend.app.browser.submission import SubmissionService

    owner_ui(request)
    await SubmissionService(session, get_settings()).stop_all()
    return {"status": "remaining_submissions_stopped"}


@router.post("/submissions/{application_id}/reconcile", response_model=Submission)
async def reconcile_submission(application_id: UUID, request: Request):
    from backend.app.browser.submission_worker import SubmissionWorker
    from backend.app.db.session import get_session_factory

    owner_ui(request)
    try:
        return await SubmissionWorker(
            get_session_factory(), get_settings(), None
        ).reconcile(application_id)
    except ValueError:
        raise HTTPException(409, "submission_not_reconcilable") from None


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


assistant_router = APIRouter(
    prefix="/api/v1/browser-applications",
    tags=["Local browser assistance"],
    route_class=ProtectedApplicationRoute,
    dependencies=[Depends(require_api_token), Depends(local_boundary)],
)


@assistant_router.get("/policy")
async def get_browser_policy():
    from backend.app.browser.asset_policy import policy

    return policy(get_settings())


@assistant_router.post("/{packet_id}/page-preview")
async def preview_current_page(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session, scope="function"),
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


@assistant_router.post(
    "/{packet_id}/resume-page", dependencies=[Depends(require_owner_approval)]
)
async def resume_current_page(
    packet_id: UUID, data: ResumePage, session: AsyncSession = Depends(get_db_session, scope="function")
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


@assistant_router.post("/{packet_id}/step-preview")
async def preview_step(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session, scope="function"),
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


@assistant_router.post(
    "/{packet_id}/advance-step", dependencies=[Depends(require_owner_approval)]
)
async def advance_application_step(
    packet_id: UUID, data: AdvanceStep, session: AsyncSession = Depends(get_db_session, scope="function")
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


@assistant_router.post("/{packet_id}/opportunity-preview")
async def preview_opportunity(
    packet_id: UUID,
    data: RevisionInput,
    session: AsyncSession = Depends(get_db_session, scope="function"),
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


@assistant_router.post(
    "/{packet_id}/company-source-preview",
    dependencies=[Depends(require_owner_approval)],
)
async def preview_company_source(
    packet_id: UUID,
    data: ReadCompanySource,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.browser.company_source import preview

    async with browser.operations.run(
        packet_id, "company_source_preview", data.expected_revision
    ):
        try:
            async with asyncio.timeout(30):
                return await preview(session, packet_id, data)
        except TimeoutError:
            raise HTTPException(
                409, "Company source reading timed out; read it manually"
            ) from None


@assistant_router.post(
    "/{packet_id}/opportunity-approve", dependencies=[Depends(require_owner_approval)]
)
async def approve_opportunity(
    packet_id: UUID,
    data: ReviewOpportunity,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.browser.opportunity import approve

    async with browser.operations.run(
        packet_id, "opportunity_approve", data.expected_revision
    ):
        try:
            async with asyncio.timeout(20):
                result = await approve(session, packet_id, data)
                await session.commit()
                return result
        except TimeoutError:
            raise HTTPException(
                409, "Context approval timed out; check saved state before retrying"
            ) from None


@assistant_router.post("")
async def prepare_application(
    data: PrepareBrowser, session: AsyncSession = Depends(get_db_session, scope="function")
):
    result = await prepare(session, data)
    await session.commit()
    return result


@assistant_router.get("/{packet_id}")
async def get_application_status(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session, scope="function")
):
    return await status(session, packet_id)


@assistant_router.get("/{packet_id}/operation")
async def get_browser_operation(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session, scope="function")
):
    packet = await ApplicationPacketService(session).repo.get(packet_id)
    return {
        "packet_revision": packet.revision,
        "active_operation": browser.operations.public(packet_id),
        "cancellation_pending": str(packet_id) in browser.operations.stopping,
    }


@assistant_router.post("/{packet_id}/open")
async def open_application(
    packet_id: UUID, data: OpenBrowser, session: AsyncSession = Depends(get_db_session, scope="function")
):
    if not data.approve_dedicated_profile or not data.confirm_destination_permission:
        raise HTTPException(
            422,
            "Explicit dedicated-profile and destination permission approval required",
        )
    from backend.app.browser.asset_policy import policy

    assets = policy(get_settings())
    if assets["origins"] and (
        not data.confirm_asset_permissions
        or data.asset_policy_digest != assets["digest"]
    ):
        raise HTTPException(
            422, "Review and approve the current public asset origins before opening"
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


@assistant_router.post("/{packet_id}/actions")
async def application_action(
    packet_id: UUID,
    data: BrowserAction,
    session: AsyncSession = Depends(get_db_session, scope="function"),
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


@assistant_router.post("/{packet_id}/submission-preview")
async def submission_preview(
    packet_id: UUID,
    data: SubmissionPreviewRequest,
    session: AsyncSession = Depends(get_db_session, scope="function"),
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


@assistant_router.post(
    "/{packet_id}/authorize-submission", dependencies=[Depends(require_owner_approval)]
)
async def authorize_submission(
    packet_id: UUID,
    data: SubmissionAuthorization,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.browser.submissions import authorize

    async with browser.operations.run(
        packet_id, "authorize_submission", data.expected_revision
    ):
        result = await authorize(session, packet_id, data)
        await session.commit()
        return result


@assistant_router.post("/{packet_id}/submit")
async def submit_approved_application(
    packet_id: UUID,
    data: SubmitApproved,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.browser.submissions import submit

    async with browser.operations.run(packet_id, "submit", data.expected_revision):
        return await submit(session, packet_id, data)


@assistant_router.post("/{packet_id}/recover-submission")
async def recover_submission(
    packet_id: UUID, session: AsyncSession = Depends(get_db_session, scope="function")
):
    from backend.app.browser.submissions import recover

    async with browser.operations.run(packet_id, "recover_submission"):
        return await recover(session, packet_id)


@assistant_router.post(
    "/{packet_id}/consent", dependencies=[Depends(require_owner_approval)]
)
async def owner_consent(
    packet_id: UUID,
    data: ConsentAction,
    session: AsyncSession = Depends(get_db_session, scope="function"),
):
    from backend.app.browser.submissions import set_consent

    async with browser.operations.run(packet_id, "consent", data.expected_revision):
        return await set_consent(session, packet_id, data)
