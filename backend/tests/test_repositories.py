"""Tests for Company, Job, and Contact repository data access layers."""

import pytest
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.job import JobRepository
from backend.app.repositories.contact import ContactRepository


@pytest.mark.asyncio
async def test_company_repository_lifecycle(db_session):
    repo = CompanyRepository(db_session)

    # 1. Create company
    company, created = await repo.get_or_create(
        name="Stripe",
        domain="stripe.com",
        linkedin_url="https://linkedin.com/company/stripe",
    )
    assert created is True
    assert company.name == "Stripe"
    assert company.domain == "stripe.com"

    # 2. Re-query same company (must deduplicate, not create duplicate)
    existing, created_again = await repo.get_or_create(
        name="Stripe Inc.",
        domain="stripe.com",
    )
    assert created_again is False
    assert existing.id == company.id

    # 3. Query by domain
    queried = await repo.get_by_domain("STRIPE.COM")
    assert queried is not None
    assert queried.id == company.id


@pytest.mark.asyncio
async def test_job_repository_deduplication(db_session):
    company_repo = CompanyRepository(db_session)
    job_repo = JobRepository(db_session)

    company, _ = await company_repo.get_or_create(name="Acme Corp", domain="acme.com")

    # 1. Save new job
    job1, created = await job_repo.save_or_update_job(
        title="Backend Engineer (Python/Go)",
        job_url="https://acme.com/jobs/123",
        source_platform="greenhouse",
        company_id=company.id,
        location="Remote",
        is_remote=True,
        match_score=85.0,
    )
    assert created is True
    assert job1.title == "Backend Engineer (Python/Go)"

    # 2. Ingest duplicate URL with updated match explanation
    job2, created2 = await job_repo.save_or_update_job(
        title="Backend Engineer (Python/Go)",
        job_url="https://acme.com/jobs/123",
        source_platform="linkedin",
        match_score=90.0,
        match_explanation="Updated score based on refreshed resume",
    )
    assert created2 is False
    assert job2.id == job1.id
    assert float(job2.match_score) == 90.0

    # 3. List jobs
    all_jobs = await job_repo.list_jobs(limit=10)
    assert len(all_jobs) == 1


@pytest.mark.asyncio
async def test_contact_repository_caching_and_provenance(db_session):
    company_repo = CompanyRepository(db_session)
    contact_repo = ContactRepository(db_session)

    company, _ = await company_repo.get_or_create(name="Linear", domain="linear.app")

    # 1. Save recruiter contact
    contact, created = await contact_repo.save_or_update_contact(
        company_id=company.id,
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role_title="Senior Technical Recruiter",
        email="jane@linear.app",
        email_status="verified",
        confidence_score=95.0,
        enrichment_source="hunter",
    )
    assert created is True

    # 2. Retrieve cached contacts for Linear
    cached = await contact_repo.get_cached_contacts_for_company(company.id)
    assert len(cached) == 1
    assert cached[0].full_name == "Jane Doe"
    assert cached[0].email_status == "verified"

    # 3. Filter by role substring
    recruiters = await contact_repo.get_cached_contacts_for_company(company.id, role_filter="recruiter")
    assert len(recruiters) == 1

    engineers = await contact_repo.get_cached_contacts_for_company(company.id, role_filter="engineer")
    assert len(engineers) == 0
