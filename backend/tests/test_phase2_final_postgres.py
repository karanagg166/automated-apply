"""Phase 2 isolated PostgreSQL 17, one runtime connection and fictional providers."""

import asyncio
import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from backend.app.ai.schemas import GenerateRequest
from backend.app.ai.usage import LLMUsageManager
from backend.app.models.application_answer import (
    ApplicationAnswerDraft,
    CandidateResource,
    LLMMonthlyUsage,
)
from backend.app.models.application_packet import (
    ApplicationPacket,
    ApplicationSubmissionEvidence,
)
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.discovery import JobSourceObservation
from backend.app.models.job import Job
from backend.app.schemas.applications import (
    AnswerGenerateInput,
    CreatePacket,
    QuestionInput,
)
from backend.app.schemas.discovery import RunRequest
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.applications.review import ApplicationReview
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.applications.tracker import ApplicationTracker
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.tests import test_public_ats_postgres as ats_fixture
from backend.tests.phase2a_fakes import PROJECT, FakeProvider
from backend.tests.phase5a_fakes import approve
from backend.tests.test_application_status_tracking import submission
from backend.tests.test_public_ats import configuration, feed, posting
from backend.tests.test_public_ats_postgres import execute, install_mock

postgres = ats_fixture.postgres

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("PROFILE_TEST_DATABASE_URL"),
        reason="Disposable local PG17 required",
    ),
]


async def test_one_connection_answer_rewrite_releases_reads(postgres):
    factory, _ = postgres
    settings = configuration()
    async with factory() as session:
        profile = await session.scalar(select(CandidateProfile))
        profile.projects = [PROJECT]
        await session.commit()
    provider = FakeProvider()
    async with factory() as session:
        service = ApplicationAnswerService(
            session,
            settings,
            provider,
            LLMUsageManager(factory, settings),
            owns_read_transaction=True,
        )
        result = await asyncio.wait_for(
            service.generate(
                GenerateRequest(
                    question="Describe a project", rewrite=True, save_draft=True
                )
            ),
            4,
        )
        assert result.status == "draft_ready", result
        await session.commit()
    async with factory() as session:
        assert len((await session.scalars(select(ApplicationAnswerDraft))).all()) == 1
        assert (await session.scalar(select(LLMMonthlyUsage))).requests == 1
    assert len(provider.calls) == 1


@pytest.mark.parametrize("adapter", [LeverAdapter, AshbyAdapter])
async def test_fictional_discovery_answer_review_handoff_restart_and_report(
    postgres, monkeypatch, adapter
):
    factory, engine = postgres
    settings = configuration()
    provider = FakeProvider()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=feed(adapter, [posting(adapter)]))

    install_mock(monkeypatch, adapter, handler)
    async with factory() as session:
        profile = await session.scalar(select(CandidateProfile))
        profile.projects, profile.verified_skills = [PROJECT], ["Python", "FastAPI"]
        resume = CandidateResource(
            candidate_profile_id=profile.id,
            resource_type="resume",
            label="Fictional approved canonical resume",
            url="https://example.org/resume.pdf",
            user_confirmed=True,
            is_primary=True,
        )
        session.add(resume)
        await session.commit()
        resume_id = resume.id
    request = RunRequest(
        source=adapter.source_name, idempotency_key="fictional-journey"
    )
    discovery = await execute(factory, request, settings)
    assert discovery["status"] == "success" and len(discovery["job_ids"]) == 1
    job_id = UUID(discovery["job_ids"][0])
    create_request = CreatePacket(
        idempotency_key="fictional-journey-packet",
        questions=[QuestionInput(question="Describe your best project")],
    )
    async with factory() as session:
        answers = ApplicationAnswerService(
            session,
            settings,
            provider,
            LLMUsageManager(factory, settings),
            owns_read_transaction=True,
        )
        service = ApplicationPacketService(session, answers)
        packet = await service.create(job_id, create_request)
        await session.commit()
        # Exercise the independently reserved optional rewrite on the one-slot pool.
        packet = await asyncio.wait_for(
            service.generate(
                packet.id,
                packet.fields[-1].id,
                AnswerGenerateInput(expected_revision=packet.revision, rewrite=True),
            ),
            4,
        )
        await session.commit()
        assert (
            packet.fields[-1].requires_review
            and packet.fields[-1].review_status == "pending"
        )
        assert packet.fields[-1].provenance.evidence_references
        packet = await approve(service, packet)
        handoff = await ApplicationReview(service).handoff(packet.id)
        assert handoff.application_url == packet.snapshot.destination.application_url
        assert packet.snapshot.resume.selected.resource_id == resume_id
        assert packet.tracking_state == "not_applied"
        packet_id, revision = packet.id, packet.revision
        await session.commit()
    # Drop pooled connections; a new session/service must reconstruct the saved journey.
    await engine.dispose()
    async with factory() as session:
        service = ApplicationPacketService(session)
        saved = await service.read(packet_id)
        assert saved.revision == saved.approved_revision == revision
        assert saved.tracking_state == "not_applied"
        assert (await session.get(Job, job_id)).status == "discovered"
        assert (
            await session.scalar(
                select(func.count()).select_from(ApplicationSubmissionEvidence)
            )
            == 0
        )
        replay = await service.create(job_id, create_request)
        assert replay.id == packet_id and replay.revision == revision
        tracker = ApplicationTracker(service)
        events = await tracker.events(packet_id)
        assert [e.event_type for e in events] == [
            "packet_created",
            "answer_generated",
            "packet_approved",
        ]
        assert all(e.created_at.tzinfo is not None for e in events)
        report = submission(saved)
        receipt = await tracker.report(packet_id, report)
        await session.commit()
        assert (
            receipt.confirmation_source == "user_reported"
            and receipt.evidence_confidence == "self_reported_unverified"
        )
        assert (await tracker.report(packet_id, report)).id == receipt.id
        assert (await service.read(packet_id)).tracking_state == "applied_manually"
        await session.commit()
    replay = await execute(factory, request, settings)
    assert replay["id"] == discovery["id"] and len(calls) == 1
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ApplicationPacket))
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(JobSourceObservation))
            == 1
        )
        assert (await session.get(Job, job_id)).status == "discovered"
