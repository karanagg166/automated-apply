import pytest
from sqlalchemy import select, func
from backend.app.models.job import Job
from backend.app.models.company import Company
from backend.app.models.discovery import JobSourceObservation
from backend.app.services.job_ingestion import JobIngestionService
from backend.tests.discovery_fakes import job


@pytest.mark.asyncio
async def test_tracking_urls_and_manual_state_preserved(db_session):
    service = JobIngestionService(db_session)
    first = await service.ingest_jobs(
        [job(original_url="https://example.com/jobs/one?utm_source=alert")]
    )
    stored = await db_session.get(Job, first.job_ids[0])
    stored.status, stored.match_explanation = (
        "applied",
        "Human note: spoke to recruiter",
    )
    stored.match_score = 84
    again = await service.ingest_jobs(
        [
            job(
                original_url="https://example.com/jobs/one/?ref=email#top",
                title="Updated title",
            )
        ]
    )
    assert again.updated_count == 1 and again.duplicate_count == 1
    assert (
        stored.status == "applied"
        and stored.match_explanation == "Human note: spoke to recruiter"
        and stored.match_score == 84
    )
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    observation = await db_session.scalar(select(JobSourceObservation))
    assert observation.provenance["deduplication"] == "source_identity"
    assert observation.last_observed_at >= observation.first_observed_at


@pytest.mark.asyncio
async def test_same_ats_job_across_platforms_keeps_observations(db_session):
    one = job(
        application_url="https://boards.greenhouse.io/acme/jobs/123?utm_source=naukri"
    )
    two = job(
        source_name="wellfound",
        source_job_id="wf2",
        original_url="https://wellfound.com/jobs/2",
        application_url="https://job-boards.greenhouse.io/acme/jobs/123",
        description="Another aggregator summary",
    )
    result = await JobIngestionService(db_session).ingest_jobs([one, two])
    assert result.inserted_count == 1 and result.updated_count == 1
    observations = (await db_session.scalars(select(JobSourceObservation))).all()
    assert {o.source for o in observations} == {"naukri", "wellfound"}
    assert len({o.job_id for o in observations}) == 1


@pytest.mark.asyncio
async def test_supporting_content_identity_and_possible_duplicates(db_session):
    service = JobIngestionService(db_session)
    result = await service.ingest_jobs(
        [
            job(),
            job(
                source_name="wellfound",
                source_job_id="two",
                original_url="https://wellfound.com/jobs/2",
            ),
        ]
    )
    assert result.inserted_count == 1
    possible = await service.ingest_jobs(
        [
            job(
                source_job_id="three",
                original_url="https://example.com/jobs/3",
                description="Similar position, insufficient evidence",
            )
        ]
    )
    assert possible.inserted_count == 1 and possible.possible_duplicates
    distinct = await service.ingest_jobs(
        [
            job(
                source_job_id="four",
                original_url="https://example.net/jobs/4",
                company_name="Different",
                company_domain="example.net",
            )
        ]
    )
    assert distinct.inserted_count == 1 and not distinct.possible_duplicates


@pytest.mark.asyncio
async def test_different_domains_same_company_display_name_remain_distinct(db_session):
    result = await JobIngestionService(db_session).ingest_jobs(
        [
            job(),
            job(
                source_job_id="other",
                original_url="https://example.org/job/1",
                company_domain="example.org",
            ),
        ]
    )
    assert result.inserted_count == 2
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 2


@pytest.mark.asyncio
async def test_unknown_company_is_not_fabricated_and_bad_record_isolated(db_session):
    result = await JobIngestionService(db_session).ingest_jobs(
        [{"title": "Invalid"}, job(company_name=None)]
    )
    assert result.inserted_count == 1 and result.rejected_count == 1
    stored = await db_session.get(Job, result.job_ids[0])
    assert stored.company_id is None and stored.discovery_metadata["quality_flags"] == [
        "company_unknown"
    ]


@pytest.mark.asyncio
async def test_database_error_rolls_back_only_record(db_session, monkeypatch):

    service = JobIngestionService(db_session)
    real = service.company_repo.get_or_create

    async def fail_one(name, domain):
        if name == "Broken":
            # Actual failed database statement poisons only its savepoint.
            db_session.add(Company(name=None))
            await db_session.flush()
        return await real(name, domain)

    monkeypatch.setattr(service.company_repo, "get_or_create", fail_one)
    result = await service.ingest_jobs(
        [
            job(company_name="Broken"),
            job(source_job_id="two", original_url="https://example.com/job/2"),
        ]
    )
    assert result.failed_count == 1 and result.inserted_count == 1
    await db_session.commit()


@pytest.mark.asyncio
async def test_outer_rollback_preserves_nothing(db_session):
    from sqlalchemy import text

    # SQLite needs an explicit outer transaction for SAVEPOINT rollback semantics.
    await db_session.execute(text("BEGIN"))
    await JobIngestionService(db_session).ingest_jobs([job()])
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_salary_evidence_is_not_combined_across_currencies(db_session):
    service = JobIngestionService(db_session)
    first = await service.ingest_jobs(
        [job(salary_min=100000, salary_currency="USD", salary_period="year")]
    )
    await service.ingest_jobs(
        [job(salary_max=2000000, salary_currency="INR", salary_period="month")]
    )
    stored = await db_session.get(Job, first.job_ids[0])
    assert (
        stored.salary_currency == "USD"
        and stored.salary_max is None
        and stored.salary_period == "year"
    )
