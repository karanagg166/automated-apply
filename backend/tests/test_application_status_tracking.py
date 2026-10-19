"""Only an explicit owner report records manual completion; receipts remain unverified."""

import pytest

from backend.app.schemas.applications import PacketEdit, SubmissionInput, TrackingInput
from backend.app.services.applications.base import ApplicationConflict
from backend.app.services.applications.tracker import ApplicationTracker
from backend.tests.phase5a_fakes import approve, create

pytestmark = pytest.mark.asyncio


def submission(packet, **kwargs):
    return SubmissionInput(
        expected_revision=packet.revision,
        idempotency_key="fictional-receipt-001",
        human_confirmed=True,
        confirmation="I submitted this application on the official website",
        **kwargs,
    )


async def test_opened_is_not_submitted_and_event_history(
    packet_service, application_target
):
    job, _ = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    tracker = ApplicationTracker(packet_service)
    packet = await tracker.track(
        packet.id,
        TrackingInput(
            expected_revision=packet.revision,
            lifecycle_state="external_application_opened",
        ),
    )
    await packet_service.session.commit()
    assert (
        packet.tracking_state == "not_applied"
        and packet.lifecycle_state == "external_application_opened"
    )
    assert packet.approved_revision == packet.revision and job.status == "discovered"
    events = await tracker.events(packet.id)
    assert [e.event_type for e in events] == [
        "packet_created",
        "packet_approved",
        "tracking_updated",
    ]
    assert all(e.evidence_id is None for e in events)


async def test_submission_is_idempotent_self_reported_and_immutable(
    packet_service, application_target
):
    job, _ = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    tracker = ApplicationTracker(packet_service)
    request = submission(packet, receipt_reference="Fictional owner receipt ABC")
    evidence = await tracker.report(packet.id, request)
    await packet_service.session.commit()
    replay = await tracker.report(packet.id, request)
    assert evidence == replay and evidence.confirmation_source == "user_reported"
    assert evidence.evidence_confidence == "self_reported_unverified"
    current = await packet_service.read(packet.id)
    assert (
        current.lifecycle_state == "user_reported_submitted"
        and current.tracking_state == "applied_manually"
    )
    assert current.readiness.state == "completed_by_user" and job.status == "discovered"
    assert (await tracker.events(packet.id))[-1].evidence_id == evidence.id
    with pytest.raises(ApplicationConflict):
        await packet_service.edit(
            packet.id,
            PacketEdit(expected_revision=current.revision, refresh_saved_data=True),
        )
    request.receipt_reference = "Different receipt"
    with pytest.raises(ApplicationConflict):
        await tracker.report(packet.id, request)


async def test_can_record_actual_completion_even_if_preparation_was_not_approved(
    packet_service, application_target
):
    packet = await create(packet_service, application_target[0])
    evidence = await ApplicationTracker(packet_service).report(
        packet.id, submission(packet)
    )
    assert evidence.human_confirmed


@pytest.mark.parametrize(
    "outcome",
    [
        "applied_manually",
        "application_rejected",
        "interview_scheduled",
        "offer_received",
    ],
)
async def test_no_status_shortcut_to_submission(
    packet_service, application_target, outcome
):
    packet = await create(packet_service, application_target[0])
    with pytest.raises(ApplicationConflict, match="submission"):
        await ApplicationTracker(packet_service).track(
            packet.id, TrackingInput(expected_revision=1, tracking_state=outcome)
        )


async def test_outcomes_and_withdrawal_preserve_submission(
    packet_service, application_target
):
    tracker = ApplicationTracker(packet_service)
    packet = await create(packet_service, application_target[0])
    await tracker.report(packet.id, submission(packet))
    await packet_service.session.commit()
    packet = await packet_service.read(packet.id)
    packet = await tracker.track(
        packet.id,
        TrackingInput(
            expected_revision=packet.revision, tracking_state="interview_scheduled"
        ),
    )
    await packet_service.session.commit()
    assert packet.lifecycle_state == "user_reported_submitted"
    with pytest.raises(ApplicationConflict, match="erase"):
        await tracker.track(
            packet.id,
            TrackingInput(
                expected_revision=packet.revision, tracking_state="not_applied"
            ),
        )
    packet = await tracker.track(
        packet.id,
        TrackingInput(expected_revision=packet.revision, lifecycle_state="withdrawn"),
    )
    assert (
        packet.lifecycle_state == "withdrawn"
        and await packet_service.repo.submission(packet.id)
    )


async def test_not_applied_incomplete_abandoned_archived(
    packet_service, application_target
):
    tracker = ApplicationTracker(packet_service)
    packet = await create(packet_service, application_target[0])
    packet = await tracker.track(
        packet.id,
        TrackingInput(expected_revision=1, tracking_state="application_incomplete"),
    )
    await packet_service.session.commit()
    assert (
        packet.lifecycle_state == "created"
        and packet.tracking_state == "application_incomplete"
    )
    packet = await tracker.track(
        packet.id,
        TrackingInput(
            expected_revision=packet.revision,
            lifecycle_state="abandoned",
            tracking_state="archived",
        ),
    )
    await packet_service.session.commit()
    assert packet.readiness.state == "manual_action_required"
    with pytest.raises(ApplicationConflict):
        await tracker.report(packet.id, submission(packet))


async def test_tracking_stale_packet_does_not_preserve_approval(
    packet_service, application_target, phase2_profile, db_session
):
    packet = await approve(
        packet_service, await create(packet_service, application_target[0])
    )
    phase2_profile.phone = "+1 555 0100"
    await db_session.commit()
    packet = await ApplicationTracker(packet_service).track(
        packet.id,
        TrackingInput(expected_revision=packet.revision, tracking_state="archived"),
    )
    assert packet.approved_revision is None and packet.readiness.stale
