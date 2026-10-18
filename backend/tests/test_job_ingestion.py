"""Tests for JobIngestionService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.repositories.job import JobRepository
from backend.app.repositories.company import CompanyRepository


@pytest.mark.asyncio
async def test_job_ingestion_lifecycle(db_session: AsyncSession):
    service = JobIngestionService(db_session)
    job_repo = JobRepository(db_session)
    company_repo = CompanyRepository(db_session)

    job1 = NormalizedJob(
        source_name="greenhouse",
        source_job_id="gh_1",
        original_url="https://job-boards.greenhouse.io/stripe/jobs/101",
        company_name="Stripe",
        company_domain="stripe.com",
        title="Software Engineer, Payments Infrastructure",
        description="Build scalable payments.",
        location="Remote, US",
        is_remote=True,
        salary_min=160000,
        salary_max=210000,
        salary_currency="$",
        skills_required=["Python", "PostgreSQL", "Kafka"],
    )

    job2 = NormalizedJob(
        source_name="remotive",
        source_job_id="rem_2",
        original_url="https://remotive.com/job/202",
        company_name="GitLab",
        company_domain="gitlab.com",
        title="Senior Backend Engineer",
        description="Async systems.",
        location="Worldwide",
        is_remote=True,
        salary_raw="$150,000",
        skills_required=["Go", "Ruby"],
    )

    result = await service.ingest_jobs([job1, job2])
    assert result.total_received == 2
    assert result.inserted_count == 2
    assert result.updated_count == 0
    assert len(result.job_ids) == 2

    # Verify company Stripe was registered
    company = await company_repo.get_by_domain("stripe.com")
    assert company is not None
    assert company.name == "Stripe"

    # Verify job1 in database
    db_job1 = await job_repo.get_by_url(job1.original_url)
    assert db_job1 is not None
    assert db_job1.title == job1.title
    assert db_job1.salary_range == "$160,000 - $210,000"

    # Test Deduplication: Re-ingest job1 with modified title
    job1_dup = job1.model_copy(update={"title": "Staff Payments Engineer"})
    dup_result = await service.ingest_jobs([job1_dup])
    assert dup_result.inserted_count == 0
    assert dup_result.updated_count == 1
