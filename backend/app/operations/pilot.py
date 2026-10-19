"""Thin orchestration of existing discovery, matching and packet services."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app.models.discovery import DiscoveryRun
from backend.app.models.job import Job
from backend.app.models.startup import StartupShortlistEntry
from backend.app.operations.configuration import OperationRejected
from backend.app.operations.onboarding import ProfileReadiness, profile_readiness
from backend.app.schemas.applications import CreatePacket, QuestionInput
from backend.app.schemas.discovery import DiscoveryQuery
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
from backend.app.services.startup_discovery.normalizer import (
    location_allowed,
    role_allowed,
)
from backend.app.services.startup_discovery.schemas import (
    StartupFilters,
    StartupRunRequest,
)
from backend.app.services.startup_discovery.service import StartupDiscoveryService

DEFAULT_ROLES = [
    "Python Developer",
    "Backend Engineer",
    "Software Engineer",
    "Full Stack Engineer",
    "AI Engineer",
    "Junior Software Engineer",
]
DEFAULT_LOCATIONS = ["India", "Bengaluru", "Delhi", "Hyderabad", "Pune"]


class PilotRequest(BaseModel):
    source: Literal["hacker_news", "arbeitnow", "remotive", "greenhouse"] = (
        "hacker_news"
    )
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    use_profile: bool = False
    prepare_packet: bool = False
    limit: int = Field(default=20, ge=1, le=20)
    roles: list[str] = Field(default_factory=list, max_length=10)
    locations: list[str] = Field(default_factory=list, max_length=10)


async def run_pilot(session, factory, settings, request):
    service = StartupDiscoveryService(session, factory, settings)
    onboarding = (
        await profile_readiness(session, live=settings.ENVIRONMENT != "testing")
        if request.use_profile
        else ProfileReadiness(status="not_inspected")
    )
    profile = await service.profile(request.use_profile)
    if request.use_profile and (profile is None or onboarding.missing):
        raise OperationRejected("verified_profile_onboarding_required")
    if request.prepare_packet and not request.use_profile:
        raise OperationRejected("explicit_profile_use_required_for_packet")
    roles = (
        request.roles
        or (profile.preferences.target_titles if profile else [])
        or DEFAULT_ROLES
    )
    locations = (
        request.locations
        or (profile.preferences.preferred_locations if profile else [])
        or DEFAULT_LOCATIONS
    )
    filters = StartupFilters(
        roles=roles,
        locations=locations,
        max_employees=50,
        include_unknown_size=True,
        remote_preference=profile.preferences.remote_preference
        if profile
        else "remote",
        use_profile=request.use_profile,
        limit=request.limit,
    )
    # Explicit query keywords are broad OR terms; strict suitability comes from saved matching.
    run = await service.run(
        StartupRunRequest(
            source=request.source,
            mode="job_led",
            idempotency_key=request.idempotency_key,
            filters=filters,
            query=DiscoveryQuery(limit=request.limit),
            allow_paid=False,
        )
    )
    # read_run marks interrupted leases recovery_required without replaying a provider.
    run = await service.read_run(UUID(run["id"]))
    child_id = run["query"].get("child_run_id")
    child = await session.get(DiscoveryRun, UUID(child_id)) if child_id else None
    job_ids = (
        [UUID(v) for v in (child.query_summary or {}).get("job_ids", [])]
        if child
        else []
    )
    jobs = (
        list((await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all())
        if job_ids
        else []
    )
    companies, matched = [], 0
    shortlisted = set(await session.scalars(select(StartupShortlistEntry.company_id)))
    for item in run["rankings"][: request.limit]:
        relevant = []
        fresh_ids = {e["job_id"] for e in item["hiring_evidence"] if e["fresh"]}
        for job in jobs:
            if (
                str(job.company_id) != item["company_id"]
                or str(job.id) not in fresh_ids
                or not role_allowed(job.title, roles)
                or not location_allowed([job.location], [job.remote_type], filters)
            ):
                continue
            match = (
                JobDiscoveryMatcher(session).match(job, profile) if profile else None
            )
            suitable = bool(
                match and match.match_score > 0 and not match.exclusion_reasons
            )
            matched += suitable
            relevant.append(
                dict(
                    job_id=str(job.id),
                    title=job.title,
                    source_url=job.job_url,
                    application_url=job.application_url,
                    source=job.source_platform,
                    profile_match=match.model_dump() if match else None,
                    suitability="candidate_match_requires_review"
                    if suitable
                    else "not_candidate_verified",
                )
            )
        companies.append(
            {
                **item,
                "jobs": relevant,
                "shortlisted": UUID(item["company_id"]) in shortlisted,
            }
        )
    packets, blockers = [], []
    if run["status"] not in {"success", "no_results"}:
        blockers.append("discovery_" + run["status"])
    if not companies:
        blockers.append("zero_relevant_companies_no_records_invented")
    if not any(c["jobs"] for c in companies):
        blockers.append("zero_relevant_job_opportunities")
    if profile is None:
        blockers.append("confirmed_candidate_profile_unavailable_or_use_not_approved")
    if request.prepare_packet:
        for company in companies:
            for listing in company["jobs"]:
                if not listing["application_url"]:
                    continue
                packets_service = ApplicationPacketService(session)
                job_id = UUID(listing["job_id"])
                packet = await packets_service.create(
                    job_id,
                    CreatePacket(
                        idempotency_key="pilot_packet_" + listing["job_id"],
                        questions=[
                            QuestionInput(
                                question="Describe your most technically challenging project"
                            )
                        ],
                    ),
                )
                await session.commit()
                packets.append(
                    dict(
                        packet_id=str(packet.id),
                        job_id=str(job_id),
                        readiness=packet.readiness.model_dump(),
                        review_status=packet.review_status,
                        review_url=f"/api/v1/application-packets/{packet.id}",
                        manual_application_url=packet.snapshot.destination.application_url,
                        submitted=False,
                    )
                )
                break
            if packets:
                break
        if not packets:
            blockers.append("no_saved_official_application_destination_for_packet")
    return dict(
        run_id=run["id"],
        source=request.source,
        discovery_status=run["status"],
        errors=run["errors"] + (child.errors if child else []),
        actual_jobs=len(jobs),
        actual_companies=len({j.company_id for j in jobs if j.company_id}),
        relevant_jobs=sum(len(c["jobs"]) for c in companies),
        candidate_matched_jobs=matched,
        company_size_evidence_coverage=sum(
            c["team_size_band"] != "unknown" for c in companies
        ),
        companies=companies,
        application_packets=packets,
        profile=onboarding.model_dump(),
        child_run_id=child_id,
        blockers=blockers,
        founder_contacts_independently_verified=0,
        public_professional_contacts_found=0,
        gemini_calls_completed=0,
        credits_consumed=0,
        emails_sent=0,
        applications_submitted=0,
    )
