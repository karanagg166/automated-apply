"""Owner-authenticated additive APIs. Provider execution stays in existing routers."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.manifest import link_manifest
from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    OwnerPreference,
    PrivateResume,
)
from backend.app.dashboard.notifications import preferences, synchronize
from backend.app.dashboard.resumes import (
    MAX_PDF,
    cipher,
    encrypt,
    extract_pdf,
    suggestions,
)
from backend.app.dashboard.schemas import (
    NotificationPreferences,
    NotificationRead,
    Preset,
    ResumeConfirm,
    ResumeImportRead,
)
from backend.app.dashboard.states import SUBMITTED
from backend.app.db.session import get_db_session
from backend.app.models.application_answer import CandidateResource
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.models.outreach import OutreachLog
from backend.app.models.startup import StartupShortlistEntry
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository


class OwnerRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def boundary(request: Request):
            await require_api_token(request)
            maximum = (
                MAX_PDF
                if request.url.path.endswith("/resumes") and request.method == "POST"
                else 65536
            )
            chunks, size = [], 0
            try:
                async with asyncio.timeout(20):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > maximum:
                            raise HTTPException(413, "Request exceeds size limit")
                        chunks.append(chunk)
            except TimeoutError:
                raise HTTPException(408, "Upload timeout") from None
            request._body = b"".join(chunks)
            response = await handler(request)
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        return boundary


router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Owner dashboard"],
    route_class=OwnerRoute,
    dependencies=[Depends(require_api_token)],
)


@router.get("/runtime")
async def dashboard_runtime():
    settings = get_settings()
    return {
        "demo_mode": settings.ENVIRONMENT == "testing" and settings.UI_FIXTURE_MODE,
        "external_notifications_enabled": False,
    }


@router.get("/connections")
async def connection_readiness():
    settings = get_settings()
    return {
        "providers": [
            dict(
                provider="gemini",
                configured=bool(settings.GEMINI_API_KEY and settings.LLM_MODEL),
                authorized=False,
                live_verified=False,
                capability="grounded_answers_after_explicit_request",
                budget=settings.LLM_MONTHLY_MAX_REQUESTS,
                next_action="Configure model and key server-side; authorize each AI generation. No resume PDF is sent by onboarding.",
            ),
            dict(
                provider="serper",
                configured=bool(
                    settings.SERPER_API_KEY and settings.PEOPLE_SEARCH_ENABLED
                ),
                authorized=settings.PUBLIC_SEARCH_RIGHTS_REVIEWED,
                live_verified=False,
                capability="permission_reviewed_company_research",
                budget=settings.SERPER_MONTHLY_LIMIT,
                next_action="Review search and retention rights, cost and consent before each research run.",
            ),
            dict(
                provider="apify",
                configured=bool(settings.APIFY_API_TOKEN),
                authorized=bool(settings.APIFY_SOURCES),
                live_verified=False,
                capability="operator_reviewed_actor_only",
                budget=settings.APIFY_MONTHLY_LIMIT_USD,
                next_action="Configure an authorized actor, terms, monthly USD budget and per-run cap. No execution from this screen.",
            ),
            dict(
                provider="notifications",
                configured=True,
                authorized=True,
                live_verified=False,
                capability="in_app_only",
                budget=0,
                next_action="Save in-app preferences. External delivery is disabled.",
            ),
        ]
    }


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_db_session)):
    async def count(model, *conditions):
        return await session.scalar(
            select(func.count()).select_from(model).where(*conditions)
        )

    submitted = select(ApplicationPacket.job_id).where(
        ApplicationPacket.lifecycle_state.in_(SUBMITTED)
    )
    return {
        "startups_discovered": await count(Company),
        "saved_jobs": await count(Job),
        "relevant_jobs": await count(Job, Job.match_score >= 70),
        "not_yet_applied": await count(
            Job, Job.id.not_in(submitted), Job.status != "applied"
        ),
        "shortlisted": await count(StartupShortlistEntry),
        "applications_prepared": await count(ApplicationPacket),
        "applications_reported_submitted": await count(
            ApplicationPacket,
            ApplicationPacket.lifecycle_state == "user_reported_submitted",
        ),
        "applications_provider_confirmed": await count(
            ApplicationPacket,
            ApplicationPacket.lifecycle_state == "provider_confirmed_submitted",
        ),
        "approved_gmail_messages": await count(
            OutreachLog, OutreachLog.approval_status == "approved"
        ),
        "outstanding_reviews": await count(
            ApplicationPacket,
            ApplicationPacket.lifecycle_state.in_(
                ["needs_input", "ready_for_review", "preparing"]
            ),
        ),
    }


@router.get("/onboarding/manifest")
async def manifest():
    return link_manifest()


@router.post("/resumes", response_model=ResumeImportRead, status_code=201)
async def upload_resume(
    request: Request,
    label: str = Query("Resume", min_length=1, max_length=200),
    session: AsyncSession = Depends(get_db_session),
):
    if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise HTTPException(415, "Use application/pdf")
    cipher()  # Fail before parsing if encrypted storage isn't configured.
    raw = await request.body()
    extracted = await extract_pdf(raw)
    ciphertext, digest = encrypt(raw)
    resume = PrivateResume(label=label, ciphertext=ciphertext, sha256=digest)
    session.add(resume)
    await session.flush()
    return ResumeImportRead(
        id=resume.id,
        label=label,
        **extracted,
        suggestions=suggestions(extracted["text"]),
        warnings=[
            "Extracted text is untrusted evidence. Review every imported field before saving.",
            "No external AI provider received this PDF.",
            "Scanned PDFs may require manual entry; no OCR is performed.",
        ],
    )


@router.get("/resumes")
async def list_resumes(session: AsyncSession = Depends(get_db_session)):
    rows = (
        await session.scalars(
            select(PrivateResume).order_by(PrivateResume.created_at.desc()).limit(100)
        )
    ).all()
    return {
        "resumes": [
            dict(
                id=r.id,
                label=r.label,
                confirmed=r.confirmed,
                resource_id=r.resource_id,
                created_at=r.created_at,
            )
            for r in rows
        ]
    }


@router.get("/resumes/{resume_id}")
async def download_resume(
    resume_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    resume = await session.get(PrivateResume, resume_id)
    if resume is None:
        raise HTTPException(404, "Private resume not found")
    return Response(
        cipher().decrypt(resume.ciphertext),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="resume.pdf"'},
    )


@router.post("/resumes/{resume_id}/confirm")
async def confirm_resume(
    resume_id: UUID,
    data: ResumeConfirm,
    session: AsyncSession = Depends(get_db_session),
):
    profile = await CandidateKnowledgeRepository(session).profile()
    resume = await session.get(PrivateResume, resume_id, with_for_update=True)
    if resume is None:
        raise HTTPException(404, "Resume not found")
    if resume.confirmed:
        return {"resource_id": resume.resource_id, "confirmed": True}
    if data.primary and await session.scalar(
        select(CandidateResource.id).where(
            CandidateResource.candidate_profile_id == profile.id,
            CandidateResource.resource_type == "resume",
            CandidateResource.is_primary.is_(True),
        )
    ):
        raise HTTPException(
            409, "Demote the existing primary resume before replacing it"
        )
    resource = CandidateResource(
        candidate_profile_id=profile.id,
        resource_type="resume",
        label=resume.label,
        url="private-resume:" + str(resume.id),
        source_type="private_upload",
        user_confirmed=True,
        is_primary=data.primary,
    )
    session.add(resource)
    await session.flush()
    resume.confirmed, resume.resource_id = True, resource.id
    return {"resource_id": resource.id, "confirmed": True}


@router.post("/jobs/{job_id}/shortlist")
async def shortlist_job(job_id: UUID, session: AsyncSession = Depends(get_db_session)):
    job = await session.get(Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in {"discovered", "reviewed", "shortlisted"}:
        job.status = "shortlisted"
    else:
        raise HTTPException(409, "This job has already progressed beyond shortlisting")
    return {"id": job.id, "status": job.status}


@router.get("/presets")
async def presets(session: AsyncSession = Depends(get_db_session)):
    record = await session.get(OwnerPreference, "startup_presets")
    return record.value if record else {"presets": []}


@router.post("/presets")
async def save_preset(data: Preset, session: AsyncSession = Depends(get_db_session)):
    record = await session.get(OwnerPreference, "startup_presets", with_for_update=True)
    values = list(record.value.get("presets", [])) if record else []
    values = [v for v in values if v["name"] != data.name] + [
        data.model_dump(mode="json")
    ]
    if len(values) > 20:
        raise HTTPException(422, "At most 20 filter presets")
    if record:
        record.value = {"presets": values}
    else:
        session.add(OwnerPreference(key="startup_presets", value={"presets": values}))
    return {"presets": values}


@router.get("/notifications", response_model=list[NotificationRead])
async def notifications(
    offset: int = Query(0, ge=0, le=100000),
    session: AsyncSession = Depends(get_db_session),
):
    return (
        await session.scalars(
            select(Notification)
            .order_by(Notification.created_at.desc(), Notification.id)
            .offset(offset)
            .limit(50)
        )
    ).all()


@router.post("/notifications/sync")
async def sync_notifications(session: AsyncSession = Depends(get_db_session)):
    return await synchronize(session)


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    item = await session.get(Notification, notification_id)
    if item is None:
        raise HTTPException(404, "Notification not found")
    item.read_at = datetime.now(timezone.utc)
    return {"read": True}


@router.get("/notification-preferences", response_model=NotificationPreferences)
async def get_notification_preferences(session: AsyncSession = Depends(get_db_session)):
    return await preferences(session)


@router.put("/notification-preferences", response_model=NotificationPreferences)
async def save_notification_preferences(
    data: NotificationPreferences, session: AsyncSession = Depends(get_db_session)
):
    record = await session.get(OwnerPreference, "notifications", with_for_update=True)
    if record:
        record.value = data.model_dump()
    else:
        session.add(OwnerPreference(key="notifications", value=data.model_dump()))
    return data


@router.get("/notification-delivery-history")
async def notification_delivery_history(
    session: AsyncSession = Depends(get_db_session),
):
    rows = (
        await session.scalars(
            select(NotificationDelivery)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "attempts": [
            dict(
                id=r.id,
                channel=r.channel,
                status=r.status,
                attempt_count=r.attempt_count,
                last_error=r.last_error,
                next_attempt_at=r.next_attempt_at,
                created_at=r.created_at,
            )
            for r in rows
        ],
        "external_delivery_enabled": False,
    }
