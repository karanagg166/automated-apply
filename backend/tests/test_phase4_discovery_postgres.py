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


async def test_concurrent_application_packets_share_one_durable_id_without_submission(postgres):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.models.application_packet import (
        ApplicationEvent,
        ApplicationPacket,
    )
    from backend.app.schemas.applications import CreatePacket
    from backend.app.services.applications.service import ApplicationPacketService

    factory, existing_engine = postgres
    async with factory() as session:
        job = Job(title="Fictional Backend Engineer", job_url="https://fictional.example/careers/123",
                  application_url="https://fictional.example/careers/123", source_platform="manual_browser")
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    engine = create_async_engine(existing_engine.url, pool_size=2, max_overflow=0)
    concurrent_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    ready, count = asyncio.Event(), 0
    async def create():
        nonlocal count
        async with concurrent_factory() as session:
            count += 1
            if count == 2:
                ready.set()
            await ready.wait()
            packet = await ApplicationPacketService(session).create(job_id, CreatePacket(idempotency_key="phase4-concurrent-packet"))
            await session.commit()
            return packet
    try:
        async with asyncio.timeout(15):
            first, second = await asyncio.gather(create(), create())
        assert first.id == second.id and first.revision == second.revision == 1
        assert first.tracking_state == second.tracking_state == "not_applied"
        async with concurrent_factory() as session:
            assert await session.scalar(select(func.count()).select_from(ApplicationPacket)) == 1
            assert await session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1
    finally:
        await engine.dispose()
