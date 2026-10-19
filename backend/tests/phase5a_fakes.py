"""Fictional application fixtures. No portal, browser, Gmail or paid provider calls."""

from datetime import datetime, timezone

from backend.app.models.application_answer import CandidateResource
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket, ReviewInput


async def target(session, profile):
    company = Company(name="Example Circuit", domain="circuit.example.org")
    session.add(company)
    await session.flush()
    job = Job(
        company_id=company.id,
        title="Backend Engineer",
        source_platform="naukri",
        job_url="https://www.naukri.com/job-listings-example-backend-123456",
        application_url="https://circuit.example.org/careers/backend",
        description="Build Python and FastAPI services with PostgreSQL.",
        skills_required=["Python", "PostgreSQL"],
        remote_type="remote",
        last_observed_at=datetime.now(timezone.utc),
    )
    resume = CandidateResource(
        candidate_profile_id=profile.id,
        resource_type="resume",
        label="Confirmed Backend Resume",
        url="https://drive.google.com/file/d/fictional-resume/view",
        is_primary=True,
        user_confirmed=True,
    )
    session.add_all([job, resume])
    await session.commit()
    return job, resume


async def create(service, job, **kwargs):
    result = await service.create(
        job.id, CreatePacket(idempotency_key="packet-fictional-001", **kwargs)
    )
    await service.session.commit()
    return result


async def approve(service, packet):
    from backend.app.services.applications.review import ApplicationReview

    result = await ApplicationReview(service).review(
        packet.id,
        ReviewInput(
            expected_revision=packet.revision,
            action="approve",
            confirm_resume=True,
            confirm_destination=True,
            reviewed_field_ids=[
                f.id for f in packet.fields if f.effective_answer and f.requires_review
            ],
        ),
    )
    await service.session.commit()
    return result
