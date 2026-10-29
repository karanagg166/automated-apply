"""Read-only matching of owner-supplied Naukri facts. Never contacts a portal or mailbox."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.naukri import matching_job
from backend.app.execution.worker import eligibility
from backend.app.local_agent.profile_confirmation import confirmation_matches
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
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
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.singleton_key == "primary")
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
        company = await session.get(Company, job.company_id) if job.company_id else None
        already_applied = await store.previously_applied(session, job)
        currentness = "already_applied" if already_applied else vacancy_review(job, now)
        fit = (
            matcher.match(
                matching_job(job), CandidateProfileRead.model_validate(profile), company
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
