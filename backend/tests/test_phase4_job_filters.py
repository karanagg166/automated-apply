"""Filters use explicit listing/company evidence and current owner approval."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.models.discovery import now
from backend.app.models.job import Job
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.experience_fit import experience_fit
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.startup_discovery.evidence import ingest_company
from backend.tests.startup_fakes import observed


@pytest.mark.parametrize("values", [{"experience_min_years": True}, {"experience_min_years": "2"},
    {"experience_min_years": 3, "experience_max_years": 1}, {"experience_min_years": float("nan")}])
def test_invalid_experience_evidence_is_rejected(values):
    with pytest.raises(ValidationError):
        NormalizedJob(source_name="manual", original_url="https://fictional.example/job", title="Engineer", **values)


def test_titles_do_not_establish_years_and_malformed_legacy_data_stays_unknown():
    job = Job(title="Junior Engineer", job_url="https://fictional.example/job", source_platform="manual", discovery_metadata={})
    assert experience_fit(job, 2) == "unknown"
    job.discovery_metadata = {"experience_min_years": "2"}
    assert experience_fit(job, 2) == "unknown"
    job.discovery_metadata = {"experience_min_years": 3}
    assert experience_fit(job, 2) == "below_minimum"
    job.discovery_metadata = {"experience_min_years": 0, "experience_max_years": 2}
    assert experience_fit(job, 3) == "outside_published_range"
    assert experience_fit(job, None) == "unknown"


async def test_job_search_evidence_filters_and_approved_experience(async_client, db_session, phase2_auth, phase2_profile):
    for index, (count, band) in enumerate([(8, "unknown"), (None, "1-10"), (25, "unknown")]):
        company = await ingest_company(db_session, observed(
            name=f"Fictional Team {index}", domain=f"team-{index}.example",
            source_company_id=f"team-{index}", employee_count=count, team_size_band=band,
            country="India",
        ))
        await JobIngestionService(db_session).ingest_jobs([NormalizedJob(
            source_name="manual", source_job_id=f"filter-{index}",
            original_url=f"https://team-{index}.example/jobs/python",
            title="Python Engineer", company_name=company.name, company_domain=company.domain,
            experience_level="Junior", experience_min_years=0, experience_max_years=3,
            country="IN", skills_required=["Python"], remote_type="hybrid",
            date_posted=now() - timedelta(days=2),
        )])
    # Newly observed does not mean newly published.
    await JobIngestionService(db_session).ingest_jobs([NormalizedJob(
        source_name="manual", source_job_id="unknown-date", original_url="https://unknown.example/job",
        title="Junior Engineer", country="IN", experience_level="Junior",
    )])
    await db_session.commit()
    path = "/api/v1/jobs/search"
    response = await async_client.get(path, headers=phase2_auth, params={"country": "India", "company_size_band": "2-10", "experience_level": "junior", "published_within_days": 3, "skill": "Python"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["jobs"][0]["company_name"] == "Fictional Team 0"
    # Broad 1-10 bands cannot establish the lower bound of 2.
    response = await async_client.get(path, headers=phase2_auth, params={"company_size_band": "11-50"})
    assert response.json()["total"] == 1
    assert response.json()["jobs"][0]["company_name"] == "Fictional Team 2"
    response = await async_client.get(path, headers=phase2_auth, params={"approved_experience_fit": "true"})
    assert response.status_code == 409
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    await db_session.commit()
    response = await async_client.get(path, headers=phase2_auth, params={"approved_experience_fit": "true"})
    assert response.status_code == 200 and response.json()["total"] == 3
    assert all(j["experience_fit"] == "within_published_range" for j in response.json()["jobs"])
    phase2_profile.version += 1
    await db_session.commit()
    response = await async_client.get(path, headers=phase2_auth, params={"approved_experience_fit": "true"})
    assert response.status_code == 409


async def test_incremental_refresh_invalidates_obsolete_experience_ranges(db_session):
    item = NormalizedJob(source_name="manual", source_job_id="range-refresh",
        original_url="https://fictional.example/jobs/range", title="Engineer",
        experience_min_years=0, experience_max_years=3)
    ingestion = JobIngestionService(db_session)
    result = await ingestion.ingest_jobs([item])
    await db_session.commit()
    from uuid import UUID
    job = await db_session.get(Job, UUID(result.job_ids[0]))
    assert experience_fit(job, 2) == "within_published_range"
    changed = item.model_copy(update={"experience_min_years": 4, "experience_max_years": 6, "last_observed_date": now()})
    result = await ingestion.ingest_jobs([changed])
    assert result.duplicate_count == 1
    await db_session.commit()
    await db_session.refresh(job)
    assert experience_fit(job, 2) == "below_minimum"
    removed = changed.model_copy(update={"experience_min_years": None, "experience_max_years": None, "last_observed_date": now()})
    await ingestion.ingest_jobs([removed])
    await db_session.commit()
    await db_session.refresh(job)
    assert experience_fit(job, 2) == "unknown"
