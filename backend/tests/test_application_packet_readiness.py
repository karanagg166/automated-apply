"""Missing requirements and stale jobs remain actionable and truthful."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.schemas.applications import PacketEdit, QuestionInput
from backend.tests.phase5a_fakes import approve, create

pytestmark = pytest.mark.asyncio


async def test_missing_required_question(packet_service, application_target):
    packet = await create(
        packet_service,
        application_target[0],
        questions=[QuestionInput(question="What is your expected salary?")],
    )
    assert packet.readiness.state == "needs_input"
    assert any("salary" in b for b in packet.readiness.blockers)


async def test_missing_resume(packet_service, application_target, db_session):
    job, resume = application_target
    resume.user_confirmed = False
    await db_session.commit()
    packet = await create(packet_service, job)
    assert packet.readiness.state == "needs_resume"


async def test_old_listing_and_missing_description_warn(
    packet_service, application_target, db_session
):
    job, _ = application_target
    job.last_observed_at, job.description = (
        datetime.now(timezone.utc) - timedelta(days=60),
        None,
    )
    await db_session.commit()
    preview = await packet_service.preview(job.id)
    assert any("outdated" in x for x in preview.readiness.warnings)
    assert any("description is missing" in x for x in preview.readiness.warnings)


async def test_missing_and_invalid_destinations(
    packet_service, application_target, db_session
):
    job, _ = application_target
    job.job_url, job.application_url = "https://other.example.org/job", None
    await db_session.commit()
    packet = await create(packet_service, job)
    assert packet.readiness.state == "needs_input"
    assert packet.snapshot.destination.kind == "unknown"
    job.application_url = "http://127.0.0.1/private"
    await db_session.commit()
    packet = await packet_service.edit(
        packet.id, PacketEdit(expected_revision=1, refresh_saved_data=True)
    )
    assert (
        packet.snapshot.destination.kind == "expired_or_invalid"
        and not packet.snapshot.destination.valid
    )


async def test_ready_does_not_mean_uploaded_or_submitted(
    packet_service, application_target
):
    packet = await approve(
        packet_service, await create(packet_service, application_target[0])
    )
    assert packet.readiness.state == "ready_for_manual_handoff"
    assert any(
        "manual_resume_upload_required" in step
        for step in packet.readiness.manual_steps
    )
    assert packet.tracking_state == "not_applied"
