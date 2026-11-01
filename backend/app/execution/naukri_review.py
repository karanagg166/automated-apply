"""Read-only matching of owner-supplied Naukri facts. Never contacts a portal or mailbox."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution.naukri import normalized_url, reviewed_job_context
from backend.app.execution.worker import eligibility
from backend.app.local_agent.profile_confirmation import confirmation_matches
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.services.applications.platforms.naukri import posting_unavailable
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher


def vacancy_review(job, now):
    evidence = (job.discovery_metadata or {}).get("data_provenance", {})
    status = evidence.get("posting_status", "unknown")
    deadline = evidence.get("valid_through")
    if deadline:
        try:
            if date.fromisoformat(deadline) < now.date():
                return "expired"
        except (TypeError, ValueError):
            return "invalid_evidence"
    if posting_unavailable(job, now):
        return "closed"
    if status == "already_applied":
        return "already_applied"
    try:
        observed = datetime.fromisoformat(evidence.get("owner_observed_at", ""))
    except (ValueError, TypeError):
        return "unverified"
    if observed.tzinfo is None or observed > now + timedelta(minutes=5):
        return "unverified"
    if now - observed > timedelta(hours=24):
        return "stale"
    return "owner_observed_active" if status == "active" else "unverified"


async def review_jobs(session, jobs):
    # Dashboard lists share one read snapshot. Never hold the small production
    # pool for per-listing company/packet/receipt round trips. Write admission
    # still performs its own fresh canonical checks under the owner fence.
    from backend.app.execution.naukri_receipts import PREFIX

    jobs = list(jobs)
    company_ids = {job.company_id for job in jobs if job.company_id}
    companies = {
        company.id: company
        for company in (await session.scalars(
            select(Company).where(Company.id.in_(company_ids))
            .execution_options(populate_existing=True)
        )).all()
    } if company_ids else {}
    terminal = ["user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown"]
    prior = (await session.execute(
        select(ApplicationPacket.job_id, Job.job_url, Job.source_platform)
        .join(Job, Job.id == ApplicationPacket.job_id)
        .where(ApplicationPacket.lifecycle_state.in_(terminal))
    )).all()
    prior_ids = {row.job_id for row in prior}
    prior_requisitions = set()
    for row in prior:
        if row.source_platform != "naukri":
            continue
        try:
            prior_requisitions.add(normalized_url(row.job_url).rsplit("-", 1)[-1])
        except (TypeError, ValueError):
            continue
    requisitions = set()
    for job in jobs:
        try:
            requisitions.add(normalized_url(job.job_url).rsplit("-", 1)[-1])
        except (TypeError, ValueError):
            continue
    receipt_keys = {prefix + req for req in requisitions for prefix in (PREFIX, "naukri_worker_receipt:")}
    retained = (await session.scalars(
        select(OwnerPreference.key).where(OwnerPreference.key.in_(receipt_keys))
    )).all() if receipt_keys else []
    # Existence, including damaged or unconfirmed evidence, prevents replay.
    prior_requisitions.update(key.rsplit(":", 1)[-1] for key in retained)
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.singleton_key == "primary")
        .execution_options(populate_existing=True)
    )
    confirmation = await session.get(OwnerPreference, "phase1_profile_confirmation")
    confirmed = confirmation_matches(
        profile, confirmation.value if confirmation else {}
    )
    matcher = JobDiscoveryMatcher(
        session
    )  # No Gmail read/import implied by this review.
    now = datetime.now(timezone.utc)
    result = []
    for job in jobs:
        try:
            normalized_url(job.job_url)
        except (ValueError, TypeError):
            result.append({"id": str(job.id), "title": job.title, "job_url": job.job_url,
                           "employer": None, "state": "REJECTED", "reason": "invalid_requisition_identity",
                           "match": None, "submission_allowed": False})
            continue
        company = companies.get(job.company_id)
        already_applied = bool(
            (job.discovery_metadata or {}).get("data_provenance", {}).get("posting_status") == "already_applied"
            or getattr(job, "application_status", None) in {
                "applied", "submitted", "interview", "offer", "applied_manually", "applied_verified",
            }
            or job.status in {"applied", "submitted"}
            or job.id in prior_ids
            or normalized_url(job.job_url).rsplit("-", 1)[-1] in prior_requisitions
        )
        job, company = reviewed_job_context(job, company)
        currentness = "already_applied" if already_applied else vacancy_review(job, now)
        fit = (
            matcher.match(
                job, CandidateProfileRead.model_validate(profile), company
            )
            if profile
            else None
        )
        state, reason = (
            eligibility(job, profile, fit)
            if fit
            else ("NEEDS_INPUT", "candidate_profile_missing")
        )
        if not confirmed:
            state, reason = "NEEDS_INPUT", "confirmed_profile_required"
        if currentness in {"closed", "expired", "invalid_evidence", "already_applied"}:
            state, reason = "REJECTED", currentness
        elif state == "ELIGIBLE" and currentness != "owner_observed_active":
            state, reason = "NEEDS_INPUT", "current_vacancy_requires_owner_review"
        result.append(
            {
                "id": str(job.id),
                "title": job.title,
                "job_url": job.job_url,
                "employer": company.name if company else None,
                "profile_version": profile.version if profile else None,
                "profile_confirmed": confirmed,
                "vacancy_review": currentness,
                "provider_verified": False,
                "state": state,
                "reason": reason,
                "match": fit.model_dump() if fit else None,
                "submission_allowed": False,
            }
        )
    return result
