"""Private discovery REST boundary. No privileged discovery runner is exposed in MCP."""

from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, func
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session, get_session_factory
from backend.app.schemas.discovery import RunRequest
from backend.app.schemas.job import JobRead
from backend.app.models.job import Job
from backend.app.models.company import Company
from backend.app.models.discovery import (
    DiscoveryRun,
    DiscoveredPerson,
    JobSourceObservation,
)
from backend.app.services.job_sources.registry import source_registry, resolve_source
from backend.app.services.job_discovery_service import (
    JobDiscoveryService,
    IdempotencyConflict,
    run_output,
)
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.services.people_discovery.base import PeopleQuery
from backend.app.services.people_discovery.service import PeopleDiscoveryService
from backend.app.services.discovery_budget import DiscoveryBudget
from backend.app.ai.usage import concurrency_limiter
from backend.app.core.config import get_settings
import asyncio

router = APIRouter(
    prefix="/api/v1", tags=["Discovery"], dependencies=[Depends(require_api_token)]
)


@router.get("/discovery/sources")
async def sources():
    return {
        "sources": [config.model_dump() for config in source_registry().values()],
        "people_search": {
            "source": "public_search",
            "enabled": get_settings().PEOPLE_SEARCH_ENABLED,
            "credentials_configured": bool(get_settings().SERPER_API_KEY),
            "read_only": True,
            "live_verified": False,
        },
    }


def service(session):
    return JobDiscoveryService(session, get_session_factory())


@router.post("/discovery/preview")
async def preview(request: RunRequest, session: AsyncSession = Depends(get_db_session)):
    return await service(session).preview(request)


@router.post("/discovery/runs")
async def start_run(
    request: RunRequest, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await service(session).run(request)
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/discovery/runs/{run_id}")
async def read_run(run_id: UUID, session: AsyncSession = Depends(get_db_session)):
    run = await session.get(DiscoveryRun, run_id)
    if run is None:
        raise HTTPException(404, "Discovery run not found")
    return run_output(run)


@router.get("/jobs/search")
async def search_jobs(
    page: int = Query(1, ge=1, le=10000),
    limit: int = Query(20, ge=1, le=100),
    platform: str | None = Query(None, max_length=100),
    role: str | None = Query(None, max_length=200),
    location: str | None = Query(None, max_length=200),
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] | None = None,
    employment_type: str | None = Query(None, max_length=50),
    minimum_match_score: float | None = Query(None, ge=0, le=100),
    max_age_days: int | None = Query(None, ge=1, le=3650),
    sort: Literal["freshness", "match", "oldest"] = "freshness",
    rank: bool = False,
    exclude_preferences: bool = True,
    session: AsyncSession = Depends(get_db_session),
):
    statement = select(Job, Company).outerjoin(Company, Job.company_id == Company.id)
    if platform:
        resolve_source(platform)
        statement = statement.where(
            or_(
                Job.source_platform == platform,
                Job.id.in_(
                    select(JobSourceObservation.job_id).where(
                        JobSourceObservation.source == platform
                    )
                ),
            )
        )
    if role:
        statement = statement.where(Job.title.icontains(role, autoescape=True))
    if location:
        statement = statement.where(Job.location.icontains(location, autoescape=True))
    if remote_type:
        statement = statement.where(Job.remote_type == remote_type)
    if employment_type:
        statement = statement.where(Job.employment_type == employment_type)
    if max_age_days:
        # Freshness means observed, not a claim of publication or accepting applications.
        statement = statement.where(
            Job.last_observed_at
            >= datetime.now(timezone.utc) - timedelta(days=max_age_days)
        )
    profile = None
    if (
        rank
        or sort == "match"
        or minimum_match_score is not None
        or exclude_preferences
    ):
        try:
            profile = await CandidateProfileService(session).get_profile()
        except ProfileNotFoundError:
            if rank or sort == "match" or minimum_match_score is not None:
                raise HTTPException(
                    409, "Save a candidate profile before requesting ranking"
                ) from None
    rows = (
        await session.execute(
            statement.order_by(Job.last_observed_at.desc().nullslast(), Job.id).limit(
                5001
            )
        )
    ).all()
    if len(rows) > 5000:
        raise HTTPException(
            422, "Narrow filters to at most 5000 jobs for deterministic ranking"
        )
    items = []
    matcher = JobDiscoveryMatcher(session)
    for job, company in rows:
        match = matcher.match(job, profile, company) if profile else None
        if match and exclude_preferences and match.exclusion_reasons:
            continue
        if minimum_match_score is not None and match.match_score < minimum_match_score:
            continue
        items.append(
            {
                **JobRead.model_validate(job).model_dump(mode="json"),
                "company_name": company.name if company else None,
                "company_domain": company.domain if company else None,
                "company_intelligence": (company.metadata_ or {}).get(
                    "startup_discovery", {}
                )
                if company
                else {},
                "first_observed_at": job.first_observed_at.isoformat()
                if job.first_observed_at
                else None,
                "country": (job.discovery_metadata or {}).get("country"),
                "region": (job.discovery_metadata or {}).get("region"),
                "skills_preferred": (job.discovery_metadata or {}).get(
                    "skills_preferred", []
                ),
                "equity": (job.discovery_metadata or {}).get("equity"),
                "quality_flags": (job.discovery_metadata or {}).get(
                    "quality_flags", []
                ),
                "application_url": job.application_url,
                "remote_type": job.remote_type,
                "employment_type": job.employment_type,
                "salary_min": float(job.salary_min)
                if job.salary_min is not None
                else None,
                "salary_max": float(job.salary_max)
                if job.salary_max is not None
                else None,
                "salary_currency": job.salary_currency,
                "salary_period": job.salary_period,
                "last_observed_at": job.last_observed_at.isoformat()
                if job.last_observed_at
                else None,
                "source_verification_status": job.source_verification_status,
                "match": match.model_dump() if match else None,
            }
        )
    if sort == "match":
        items.sort(key=lambda item: -item["match"]["match_score"])
    elif sort == "oldest":
        items.reverse()
    selected = items[(page - 1) * limit : page * limit]
    by_id = {item["id"]: item for item in selected}
    for item in selected:
        item["source_observations"] = []
    if selected:
        # Bound evidence output per job, without letting one frequently observed job hide others.
        recent = (
            select(
                JobSourceObservation,
                func.row_number()
                .over(
                    partition_by=JobSourceObservation.job_id,
                    order_by=(
                        JobSourceObservation.last_observed_at.desc(),
                        JobSourceObservation.id,
                    ),
                )
                .label("position"),
            )
            .where(JobSourceObservation.job_id.in_([UUID(key) for key in by_id]))
            .subquery()
        )
        observation_model = aliased(JobSourceObservation, recent)
        observations = (
            await session.scalars(
                select(observation_model).where(recent.c.position <= 20)
            )
        ).all()
        for observation in observations:
            by_id[str(observation.job_id)]["source_observations"].append(
                {
                    "source": observation.source,
                    "source_job_id": observation.source_job_id,
                    "original_url": observation.original_url,
                    "first_observed_at": observation.first_observed_at.isoformat(),
                    "last_observed_at": observation.last_observed_at.isoformat(),
                    "provenance": observation.provenance,
                    "verification_status": observation.verification_status,
                }
            )
    return {"total": len(items), "page": page, "limit": limit, "jobs": selected}


@router.post("/discovery/people/search")
async def people_search(
    query: PeopleQuery, session: AsyncSession = Depends(get_db_session)
):
    settings = get_settings()
    try:
        async with asyncio.timeout(settings.DISCOVERY_TIMEOUT_SECONDS):
            async with concurrency_limiter(settings.DISCOVERY_MAX_CONCURRENCY):
                return await PeopleDiscoveryService(
                    session, DiscoveryBudget(get_session_factory())
                ).search(query)
    except TimeoutError:
        raise HTTPException(
            504, "Public search timed out; reserved credit retained"
        ) from None


@router.get("/companies/{company_id}/people")
async def company_people(
    company_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    if await session.get(Company, company_id) is None:
        raise HTTPException(404, "Company not found")
    records = (
        await session.scalars(
            select(DiscoveredPerson)
            .where(DiscoveredPerson.company_id == company_id)
            .order_by(DiscoveredPerson.observed_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "people": [
            {
                "name": p.name,
                "role": p.role,
                "linkedin_url": p.linkedin_url,
                "evidence_url": p.evidence_url,
                "source": p.source,
                "observed_at": p.observed_at.isoformat(),
                "verification_status": p.verification_status,
                "evidence": p.evidence,
                "outreach_mode": "manual",
            }
            for p in records
        ]
    }
