"""Authenticated owner dashboard contract; no credential forms or submit route."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.router import owner_ui
from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.core.security import require_api_token
from backend.app.dashboard.models import OwnerPreference
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.execution import questions, recurring, store
from backend.app.execution.contracts import (
    AutomationControl,
    AutomationPolicyUpdate,
    Configuration,
    Control,
    ImportBatch,
    QuestionAnswer,
    Start,
)
from backend.app.execution.naukri import capability_matrix, normalize
from backend.app.execution.naukri_review import review_jobs
from backend.app.execution.queue_contracts import (
    Platform,
    QueueControl,
    QueuePolicyUpdate,
    Stage,
)
from backend.app.execution.worker import needs_owner_answer
from backend.app.models.job import Job
from backend.app.schemas.applications import RevisionInput
from backend.app.services.applications.base import ApplicationError
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.job_ingestion import JobIngestionService

router = APIRouter(
    prefix="/api/v1/execution",
    tags=["Job execution"],
    route_class=OwnerRoute,
    dependencies=[Depends(require_api_token)],
)


@router.get("/queue")
async def application_queue_status(
    platform: Platform | None = None, stage: Stage | None = None,
    search: str | None = Query(None, max_length=200),
    location: str | None = Query(None, max_length=200),
    minimum_score: int | None = Query(None, ge=0, le=100),
    limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
):
    from backend.app.execution.application_queue import listing

    return await listing(session, platform=platform, stage=stage, search=search, location=location,
                         minimum_score=minimum_score, limit=limit, offset=offset)


@router.put("/queue/policy")
async def application_queue_policy(
    data: QueuePolicyUpdate, request: Request, session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    from backend.app.execution.application_queue import configure

    try:
        return await configure(session, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/queue/control")
async def application_queue_control(
    data: QueueControl, request: Request, session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    from backend.app.execution.application_queue import control

    try:
        return await control(session, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/naukri")
async def status(session: AsyncSession = Depends(get_db_session)):
    from backend.app.local_agent.platforms import platform_connections

    return {
        "automation": await recurring.status(session),
        "capabilities": capability_matrix(),
        "configuration": await store.configuration(session),
        "executions": [r.value for r in await store.rows(session) if r.value["platform"] == "naukri"],
        "worker_requirement": "awake_local_worker_or_separately_approved_always_on_worker",
        "submitted": False,
        "account_session": next(item for item in await platform_connections(session) if item["platform"] == "naukri"),
    }


@router.put("/naukri/automation/policy")
async def automation_policy(data: AutomationPolicyUpdate, request: Request, session: AsyncSession = Depends(get_db_session)):
    owner_ui(request)
    try:
        return await recurring.configure(session, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/naukri/automation/control")
async def automation_control(data: AutomationControl, request: Request, session: AsyncSession = Depends(get_db_session)):
    owner_ui(request)
    try:
        return await recurring.control(session, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.put("/naukri")
async def configure(
    data: Configuration,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        await store.configure(session, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None
    return data


@router.post("/naukri/import")
async def imports(
    data: ImportBatch, request: Request, session: AsyncSession = Depends(get_db_session)
):
    owner_ui(request)
    try:
        await store.memory_row(session, lock=True)
        for item in data.jobs:
            if item.alert_candidate_id:
                from backend.app.execution.alert_email import PREFIX
                from backend.app.execution.naukri import normalized_url
                candidate = await session.get(OwnerPreference, PREFIX + str(item.alert_candidate_id))
                if not candidate or candidate.value.get("state") != "NEEDS_INPUT" or candidate.value["expires_at"] <= (await instant(session)).isoformat() or normalized_url(item.url) != candidate.value["url"]:
                    raise ValueError("current_alert_candidate_required")
                item.provenance = "owner_job_alert"
                item.message_reference = "gmail-alert:" + str(item.alert_candidate_id)
                candidate.value = {**candidate.value, "state": "OWNER_REVIEWED", "reviewed_at": (await instant(session)).isoformat()}
        items = [normalize(item) for item in data.jobs]
    except ValueError:
        raise HTTPException(422, "invalid_naukri_import") from None
    result = await JobIngestionService(session).ingest_jobs(items, owner_reviewed_naukri=True)
    for job_id in result.job_ids:
        job = await session.get(Job, UUID(job_id))
        if job.source_platform != "naukri":
            continue
        source_id = job.job_url.rsplit("-", 1)[-1]
        item = next(
            (item for item in reversed(items) if item.source_job_id == source_id), None
        )
        if item:
            # An explicit owner re-import replaces current listing criteria,
            # retaining the ingestion service's human status/history guarantees.
            job.discovery_metadata = item.model_dump(mode="json")
    return result


@router.post("/naukri/apply", status_code=202)
async def start(
    data: Start, request: Request, session: AsyncSession = Depends(get_db_session)
):
    owner_ui(request)
    try:
        return await store.start(session, data.job_ids)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/{execution_id}/control")
async def control(
    execution_id: UUID,
    data: Control,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        return await store.control(
            session, execution_id, data.action, data.expected_revision
        )
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/{execution_id}/questions/{field_id}")
async def ask(
    execution_id: UUID,
    field_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        return await questions.ask(session, execution_id, field_id)
    except (ToolDenied, ValueError) as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/questions")
async def pending(session: AsyncSession = Depends(get_db_session)):
    return [
        r.value
        for r in (
            await session.scalars(
                select(OwnerPreference).where(
                    OwnerPreference.key.startswith(questions.PREFIX)
                )
            )
        ).all()
    ]


@router.post("/questions/{question_id}/approve-reuse")
async def reuse(
    question_id: UUID, request: Request, session: AsyncSession = Depends(get_db_session)
):
    owner_ui(request)
    try:
        return await questions.approve_reuse(session, question_id)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/packets/{packet_id}/questions/{field_id}")
async def ask_packet_question(
    packet_id: UUID,
    field_id: UUID,
    data: RevisionInput,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        await store.memory_row(session, lock=True)
        packet = await ApplicationPacketService(session).read(packet_id)
        if packet.revision != data.expected_revision:
            raise ToolDenied("packet_revision_conflict")
        field = next((f for f in packet.fields if f.id == field_id), None)
        if not field or not needs_owner_answer(field, await instant(session)):
            raise ToolDenied("missing_or_expired_answer_required")
        questions.permitted(field.question)
        intent = await store.packet_question_intent(session, packet)
        return await questions.ask(session, intent["id"], field_id)
    except ApplicationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except (ToolDenied, ValueError) as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/questions/{question_id}/answer")
async def answer_question(
    question_id: UUID,
    data: QuestionAnswer,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        return await questions.answer_dashboard(
            session, question_id, data.answer, data.expected_revision
        )
    except ApplicationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except (ToolDenied, ValueError) as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/naukri/jobs")
async def find_saved(session: AsyncSession = Depends(get_db_session)):
    rows = (
        await session.scalars(
            select(Job)
            .where(Job.source_platform == "naukri")
            .order_by(Job.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "jobs": await review_jobs(session, rows),
        "source": "owner_imports",
        "portal_search_executed": False,
    }


@router.get("/events")
async def events(session: AsyncSession = Depends(get_db_session)):
    return await store.events(session)


@router.post("/events/{event_id}/ack")
async def acknowledge(
    event_id: UUID, request: Request, session: AsyncSession = Depends(get_db_session)
):
    owner_ui(request)
    try:
        await store.acknowledge(session, event_id)
    except ToolDenied as exc:
        raise HTTPException(404, str(exc)) from None
    return {"acknowledged": True}


@router.post("/{execution_id}/questions/{field_id}/reuse/{question_id}")
async def reuse_for(
    execution_id: UUID,
    field_id: UUID,
    question_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        return await questions.reuse_for(session, question_id, execution_id, field_id)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None
