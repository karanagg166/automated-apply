"""Real discovery, evidence-based filtering, and deterministic saved-profile matching."""
import re
from uuid import UUID

from sqlalchemy import select

from backend.app.dashboard.states import SUBMITTED
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.models.startup import CompanySourceObservation
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.schemas.discovery import DiscoveryQuery, RunRequest
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
from backend.app.services.job_discovery_service import JobDiscoveryService
from backend.app.services.startup_discovery.intelligence import company_size
from backend.app.services.startup_discovery.normalizer import BANDS

FREE_SOURCES = {"greenhouse", "arbeitnow", "remotive", "hacker_news"}


async def discover(factory, settings, campaign):
    """Outside campaign transactions. A lost discovery response is inspected, never replayed."""
    filters = campaign.plan.filters
    if filters.source == "cached":
        return {"status": "cached", "provider_calls": 0}
    if filters.source not in FREE_SOURCES:
        return {"status": "manual_required", "error_code": "free_discovery_not_connected",
                "source": filters.source, "automated_application_connected": False}
    async with factory() as session:
        result = await JobDiscoveryService(session, factory, settings).run(RunRequest(
            source=filters.source, use_profile=False, allow_paid=False,
            query=DiscoveryQuery(keywords=[filters.role] if filters.role else [],
                                 locations=[filters.location] if filters.location else [],
                                 remote_preference=filters.remote, limit=100),
            idempotency_key=f"agent_{campaign.id.hex}"))
    return {"status": result["status"], "discovery_run_id": result["id"],
            "job_ids": result["job_ids"], "counts": result["counts"], "source": filters.source}


def filter_evidence(job, company, observations, filters):
    """Only confirmed matches enter the positional result list; unknowns remain explicit."""
    unknown, excluded = [], []
    title, description = job.title.casefold(), (job.description or "").casefold()
    if filters.role:
        terms = re.findall(r"[\w+#]+", filters.role.casefold())
        if not all(term in title or (term in {"python", "fastapi"} and term in description) for term in terms):
            excluded.append("role")
    if filters.skills:
        required = {s.casefold() for s in job.skills_required}
        if not required:
            unknown.append("skills")
        elif not all(s.casefold() in required for s in filters.skills):
            excluded.append("skills")
    if filters.location:
        if not job.location:
            unknown.append("location")
        elif filters.location.casefold() not in job.location.casefold():
            excluded.append("location")
    if filters.remote not in (None, "any"):
        if job.remote_type == "unknown":
            unknown.append("remote_policy")
        elif filters.remote != job.remote_type:
            excluded.append("remote_policy")
    if filters.exclude_internships:
        if job.employment_type == "internship" or "intern" in title:
            excluded.append("internship")
        elif not job.employment_type:
            unknown.append("employment_type")
    startup = (company.metadata_ or {}).get("startup_discovery", {}) if company else {}
    if filters.startup and not (startup.get("source") == "work_at_a_startup" or
                                startup.get("stage") in {"pre_seed", "seed", "early", "startup"}):
        unknown.append("startup_status")
    size = company_size(observations)
    if filters.minimum_employees is not None or filters.maximum_employees is not None:
        low = high = size["employee_count"]
        if low is None:
            low, high = BANDS.get(size["team_size_band"], (None, None))
        if low is None or high is None:
            unknown.append("company_size")
        elif ((filters.minimum_employees is not None and low < filters.minimum_employees) or
              (filters.maximum_employees is not None and high > filters.maximum_employees)):
            if low != high:
                unknown.append("company_size_bounds")
            else:
                excluded.append("company_size")
    if filters.minimum_experience is not None or filters.maximum_experience is not None:
        # No seniority-to-years inference. Only explicit numeric source facts count.
        meta = job.discovery_metadata or {}
        low, high = meta.get("experience_min_years"), meta.get("experience_max_years")
        if type(low) not in (int, float) or type(high) not in (int, float):
            unknown.append("experience_requirements")
        elif ((filters.minimum_experience is not None and low < filters.minimum_experience) or
              (filters.maximum_experience is not None and high > filters.maximum_experience)):
            excluded.append("experience_requirements")
    if filters.minimum_salary is not None:
        if (not filters.salary_currency or not filters.salary_period or
                job.salary_currency != filters.salary_currency or job.salary_period != filters.salary_period or
                job.salary_min is None):
            unknown.append("salary_comparison")
        elif float(job.salary_min) < filters.minimum_salary:
            excluded.append("salary")
    return excluded, unknown, size


async def saved_results(session, campaign, memory, *, search):
    filters = campaign.plan.filters
    query = select(Job).where(Job.status != "archived")
    if not search:
        query = query.where(Job.id.in_([UUID(i) for i in memory.get("candidate_ids", memory.get("job_ids", []))]))
    elif filters.source != "cached":
        run = next((r for r in campaign.results if r.get("tool") == "discovery"), {})
        query = query.where(Job.id.in_([UUID(i) for i in run.get("job_ids", [])]))
    # Bound the scan independently from the number returned. Stable snapshot IDs are persisted.
    jobs = list((await session.scalars(query.order_by(Job.created_at.desc(), Job.id).limit(100))).all())
    companies = {c.id: c for c in (await session.scalars(select(Company).where(
        Company.id.in_([j.company_id for j in jobs if j.company_id])))).all()}
    observations = (await session.scalars(select(CompanySourceObservation).where(
        CompanySourceObservation.company_id.in_(list(companies))))).all()
    applied_jobs = select(ApplicationPacket.job_id).where(ApplicationPacket.lifecycle_state.in_(SUBMITTED))
    applied = (await session.execute(select(Job.company_id, Job.id).where(
        (Job.status == "applied") | Job.id.in_(applied_jobs)))).all()
    applied_ids, applied_companies = {r.id for r in applied}, {r.company_id for r in applied if r.company_id}
    eligible, uncertain, rejected = [], [], 0
    for job in jobs:
        if filters.exclude_applied and (job.id in applied_ids or job.company_id in applied_companies):
            rejected += 1
            continue
        company = companies.get(job.company_id)
        excluded, unknown, size = filter_evidence(job, company, [o for o in observations if o.company_id == job.company_id], filters)
        row = {"job_id": str(job.id), "title": job.title, "company": company.name if company else None,
               "source": job.source_platform, "evidence_url": job.job_url,
               "verification_status": job.source_verification_status, "unknown_fields": unknown,
               "employee_count": size["employee_count"], "size_evidence": size["team_size_evidence"]}
        if excluded:
            rejected += 1
        elif unknown:
            uncertain.append(row)
        else:
            eligible.append(row)
    campaign.candidate_ids = [j.id for j in jobs]
    campaign.ranked_jobs = eligible[:10]
    # All eligible IDs retained for rank step; never model-supplied IDs.
    return {"status": "results", "scanned": len(jobs), "matched": len(eligible),
            "rejected": rejected, "unknown": len(uncertain), "unknown_results": uncertain[:10],
            "jobs": eligible, "scan_limit": 100, "evidence_mode": "saved_database"}


async def rank(session, campaign, limit):
    from backend.app.local_agent.knowledge import reviewed_profile
    profile = await reviewed_profile(session)
    profile = CandidateProfileRead.model_validate(profile) if profile else None
    prior = next((r for r in reversed(campaign.results) if r.get("tool") in {"search_jobs", "filter_jobs"}), {})
    rows = []
    for row in prior.get("jobs", []):
        job = await session.get(Job, UUID(row["job_id"]))
        company = await session.get(Company, job.company_id) if job.company_id else None
        match = JobDiscoveryMatcher(session).match(job, profile, company).model_dump() if profile else {
            "match_score": None, "unknown_fields": ["reviewed_candidate_profile"],
            "exclusion_reasons": [], "explanation": "Profile review required for personalized ranking."}
        if not match["exclusion_reasons"]:
            rows.append({**row, "ranking": match})
    rows.sort(key=lambda row: (-(row["ranking"]["match_score"] or 0), row["job_id"]))
    campaign.ranked_jobs = rows[:limit]
    return {"status": "ranked", "jobs": campaign.ranked_jobs,
            "personalized": profile is not None, "profile_version": profile.version if profile else None}
