"""Persistent packets and idempotency must not disturb existing jobs or answers."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.app.models.application_answer import (
    ApplicationAnswerDraft,
    LLMMonthlyUsage,
)
from backend.app.models.application_packet import ApplicationPacket
from backend.app.schemas.applications import (
    CreatePacket,
    QuestionInput,
    QuestionsAdd,
    RevisionInput,
)
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationInvalid,
    ApplicationNotFound,
)
from backend.tests.phase5a_fakes import create

pytestmark = pytest.mark.asyncio


async def test_preview_is_read_only_no_provider(
    packet_service, application_target, db_session
):
    job, _ = application_target
    result = await packet_service.preview(job.id)
    assert result.snapshot.job_title == job.title
    assert result.snapshot.match.matched_skills == ["Python"]
    assert result.readiness.state == "needs_review"
    assert result.submission_mode == "manual_handoff"
    for model in [ApplicationPacket, ApplicationAnswerDraft, LLMMonthlyUsage]:
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert packet_service.builder.answers.answer_service.provider.calls == []


async def test_durable_creation_and_idempotent_replay(
    packet_service, application_target, db_session
):
    job, resume = application_target
    packet = await create(packet_service, job)
    replay = await create(packet_service, job)
    assert replay.id == packet.id and replay.revision == 1
    assert replay.snapshot.resume.selected.resource_id == resume.id
    assert replay.snapshot.resume.selected.resource_version
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationPacket))
        == 1
    )
    assert job.status == "discovered"


@pytest.mark.parametrize("change", ["key", "body", "job"])
async def test_conflicting_idempotency_or_candidate_job(
    packet_service, application_target, db_session, change
):
    from backend.app.models.job import Job

    job, _ = application_target
    await create(packet_service, job)
    data = CreatePacket(idempotency_key="packet-fictional-001")
    if change == "key":
        data.idempotency_key = "packet-fictional-002"
    elif change == "body":
        data.questions = [QuestionInput(question="Phone number")]
    else:
        other = Job(
            title="Other role",
            source_platform="naukri",
            job_url="https://www.naukri.com/example-other",
        )
        db_session.add(other)
        await db_session.commit()
        job = other
    with pytest.raises(ApplicationConflict):
        await packet_service.create(job.id, data)


async def test_questions_and_no_cross_object_id_confusion(
    packet_service, application_target
):
    job, _ = application_target
    packet = await create(packet_service, job)
    packet = await packet_service.add_questions(
        packet.id,
        QuestionsAdd(
            expected_revision=1,
            questions=[
                QuestionInput(question="What is your notice period?"),
            ],
        ),
    )
    await packet_service.session.commit()
    assert packet.fields[-1].proposed_answer == "30 days" and packet.revision == 2
    with pytest.raises(ApplicationNotFound):
        await packet_service.generate(
            packet.id, uuid4(), RevisionInput(expected_revision=2)
        )
    with pytest.raises(ApplicationConflict):
        await packet_service.add_questions(
            packet.id,
            QuestionsAdd(
                expected_revision=1, questions=[QuestionInput(question="Email")]
            ),
        )


async def test_missing_job(packet_service):
    with pytest.raises(ApplicationNotFound):
        await packet_service.preview(uuid4())


async def test_missing_profile_preview_and_create(packet_service, db_session):
    from backend.app.models.job import Job

    job = Job(
        title="Engineer",
        source_platform="naukri",
        job_url="https://www.naukri.com/example-role",
    )
    db_session.add(job)
    await db_session.commit()
    result = await packet_service.preview(job.id)
    assert (
        result.readiness.state == "needs_profile" and result.snapshot.candidate is None
    )
    with pytest.raises(ApplicationInvalid):
        await packet_service.create(
            job.id, CreatePacket(idempotency_key="missing-profile")
        )


async def test_limit_total_questions(packet_service, application_target):
    job, _ = application_target
    packet = await create(
        packet_service,
        job,
        questions=[QuestionInput(question=f"Custom {i}") for i in range(50)],
    )
    with pytest.raises(ApplicationInvalid, match="100"):
        await packet_service.add_questions(
            packet.id,
            QuestionsAdd(
                expected_revision=1,
                questions=[QuestionInput(question=f"More {i}") for i in range(50)],
            ),
        )


async def test_observation_provenance_handles_canonical_ats_and_duplicate_observations(
    packet_service, application_target, db_session
):
    from backend.app.models.discovery import JobSourceObservation
    from backend.app.services.applications.resume_selector import digest

    job, _ = application_target
    original = job.job_url
    job.source_platform, job.job_url = (
        "greenhouse",
        "https://boards.example.org/backend",
    )
    for identity in ["source-listing-1", "source-listing-2"]:
        db_session.add(
            JobSourceObservation(
                job_id=job.id,
                source="naukri",
                identity_key=digest(identity),
                original_url=original,
            )
        )
    await db_session.commit()
    packet = await create(packet_service, job)
    assert (
        packet.platform == "naukri"
        and packet.snapshot.destination.source_confidence == "source_consistent"
    )
    assert packet.snapshot.source_observation_urls == [original]
    assert packet.snapshot.destination.application_url == job.application_url
    assert (await create(packet_service, job)).id == packet.id


async def test_unknown_platform_readiness_is_unsupported(
    packet_service, application_target, db_session
):
    job, _ = application_target
    job.source_platform, job.job_url = (
        "future_platform",
        "https://jobs.example.org/future",
    )
    await db_session.commit()
    assert (await packet_service.preview(job.id)).readiness.state == "unsupported"
