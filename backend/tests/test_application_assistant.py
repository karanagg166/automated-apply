"""Tests for ApplicationAssistant matching and safety policies."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.job import Job
from backend.app.models.company import Company
from backend.app.services.application_assistant import (
    ApplicationAssistant,
    CandidateProfile,
)


@pytest.fixture
def sample_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Karan Aggarwal",
        email="karan@example.com",
        phone="+91-9876543210",
        linkedin_url="https://linkedin.com/in/karanagg",
        github_url="https://github.com/karanagg",
        verified_skills=["Python", "FastAPI", "PostgreSQL", "Docker", "AsyncIO"],
        verified_experience_years=4.5,
        verified_roles=[
            {
                "company": "Tech Corp",
                "role": "Senior Backend Engineer",
                "highlight": "scalable event-driven APIs",
            }
        ],
        preferred_locations=["Bengaluru", "Remote"],
        remote_preference="remote_only",
        target_titles=["Backend Engineer", "Senior Software Engineer", "Python Developer"],
    )


@pytest.mark.asyncio
async def test_job_match_scoring(db_session: AsyncSession, sample_profile: CandidateProfile):
    assistant = ApplicationAssistant(db_session)

    job = Job(
        title="Senior Backend Engineer - Python",
        job_url="https://jobs.example.com/senior-backend-101",
        source_platform="greenhouse",
        location="Remote, India",
        is_remote=True,
        skills_required=["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
        description="Looking for an experienced backend engineer.",
    )
    db_session.add(job)
    await db_session.flush()

    match_result = assistant.calculate_match(job, sample_profile)
    assert match_result.match_score >= 70.0
    assert "Python" in match_result.matched_skills
    assert "Kubernetes" in match_result.missing_skills
    assert match_result.title_match is True
    assert match_result.location_match is True


@pytest.mark.asyncio
async def test_application_draft_generation_and_zero_fabrication(
    db_session: AsyncSession, sample_profile: CandidateProfile
):
    assistant = ApplicationAssistant(db_session)
    job = Job(
        title="Python Developer",
        job_url="https://jobs.example.com/dev-202",
        source_platform="arbeitnow",
        is_remote=True,
        skills_required=["Python", "PostgreSQL"],
    )
    db_session.add(job)
    await db_session.flush()

    draft = assistant.generate_draft_application(job, "Acme AI", sample_profile)
    assert draft.job_id == str(job.id)
    assert draft.company_name == "Acme AI"
    assert draft.submission_allowed is True
    assert "Tech Corp" in draft.tailored_cover_letter
    assert "4.5 years" in draft.tailored_cover_letter
    assert draft.prepared_answers["Full Name"] == "Karan Aggarwal"
    assert draft.prepared_answers["Email Address"] == "karan@example.com"


@pytest.mark.asyncio
async def test_strict_linkedin_application_prohibition(
    db_session: AsyncSession, sample_profile: CandidateProfile
):
    assistant = ApplicationAssistant(db_session)
    linkedin_job = Job(
        title="Senior Python Architect",
        job_url="https://www.linkedin.com/jobs/view/999888777",
        source_platform="linkedin",
        is_remote=True,
    )
    db_session.add(linkedin_job)
    await db_session.flush()

    draft = assistant.generate_draft_application(linkedin_job, "Global Corp", sample_profile)
    assert draft.submission_allowed is False
    assert "LinkedIn automated application submission is strictly prohibited" in draft.policy_disclaimer


@pytest.mark.asyncio
async def test_update_application_status_lifecycle(db_session: AsyncSession):
    assistant = ApplicationAssistant(db_session)
    job = Job(
        title="Backend Engineer",
        job_url="https://example.com/job/404",
        source_platform="remotive",
        status="discovered",
    )
    db_session.add(job)
    await db_session.flush()

    updated = await assistant.update_application_status(
        str(job.id),
        new_status="applied",
        notes="Applied manually on company portal after review.",
    )
    assert updated.status == "applied"
    assert "Applied manually" in (updated.match_explanation or "")
