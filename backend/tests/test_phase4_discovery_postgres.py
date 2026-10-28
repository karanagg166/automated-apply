"""New source paths use the existing transactional and idempotent PostgreSQL engine."""

import os

import httpx
import pytest
from sqlalchemy import func, select

from backend.app.models.discovery import JobSourceObservation
from backend.app.models.job import Job
from backend.app.schemas.discovery import RunRequest
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_discovery_service import JobDiscoveryService
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.smartrecruiters import SmartRecruitersAdapter
from backend.tests.test_phase4_smartrecruiters import config, fixture_handler, posting
from backend.tests.test_public_ats_postgres import postgres as ats_postgres

postgres = ats_postgres

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("PROFILE_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required")]


async def test_smartrecruiters_ingestion_cross_source_dedup_and_incremental_replay(postgres, monkeypatch):
    factory, _ = postgres
    settings, calls = config(), []
    def adapter(source, **kwargs):
        assert source == "smartrecruiters"
        return SmartRecruitersAdapter(httpx.AsyncClient(transport=httpx.MockTransport(fixture_handler([posting()], calls))), settings)
    monkeypatch.setattr(JobSourceFactory, "get_adapter", adapter)
    request = RunRequest(source="smartrecruiters", use_profile=False, idempotency_key="phase4-smart-001")
    async with factory() as session:
        result = await JobDiscoveryService(session, factory, settings).run(request)
        assert result["status"] == "success" and result["counts"]["inserted"] == 1
        replay = await JobDiscoveryService(session, factory, settings).run(request)
        assert replay["id"] == result["id"] and len(calls) == 2
        # An owner-imported link to the exact same ATS identity adds evidence, not a vacancy.
        duplicate = await JobIngestionService(session).ingest_jobs([NormalizedJob(
            source_name="manual", original_url="https://fictional-board.example/job/123",
            application_url=posting()["applyUrl"], title="Junior Python Engineer",
            company_name="Fictional Labs",
        )])
        assert duplicate.duplicate_count == 1 and duplicate.inserted_count == 0
        await session.commit()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert await session.scalar(select(func.count()).select_from(JobSourceObservation)) == 2
        await session.commit()
        refreshed = await JobDiscoveryService(session, factory, settings).run(
            request.model_copy(update={"idempotency_key": "phase4-smart-002"}))
        assert refreshed["counts"]["duplicate"] == 1 and refreshed["counts"]["inserted"] == 0
        assert len(calls) == 4


@pytest.mark.parametrize("source,url", [
    ("simplify", "https://simplify.jobs/p/fictional-engineer"),
    ("workday", "https://fictional.wd5.myworkdayjobs.com/en-US/External/job/India/Engineer_R123"),
    ("company_careers", "https://fictional-company.example/careers/engineer"),
])
async def test_manual_only_sources_import_factual_records_without_any_provider_call(postgres, monkeypatch, source, url):
    factory, _ = postgres
    def unexpected(*args, **kwargs):
        pytest.fail("Manual source attempted a provider call")
    monkeypatch.setattr(JobSourceFactory, "get_adapter", unexpected)
    request = RunRequest(source=source, use_profile=False, idempotency_key="manual-phase4-001", manual_jobs=[{
        "source_name": source, "original_url": url, "title": "Owner-reviewed fictional engineer",
        "source_verification_status": "verified", "is_confirmed_current": True,
    }])
    async with factory() as session:
        result = await JobDiscoveryService(session, factory, config()).run(request)
        assert result["status"] == "success" and result["counts"]["inserted"] == 1
        job = await session.scalar(select(Job))
        assert job.source_verification_status == "requires_review"
        assert job.discovery_metadata["is_confirmed_current"] is False
        await session.commit()
        again = await JobDiscoveryService(session, factory, config()).run(request)
        assert again["id"] == result["id"]
