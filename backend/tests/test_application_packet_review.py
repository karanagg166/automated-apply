"""Approval is an exact human review, never a submission trigger."""

from uuid import uuid4

import pytest

from backend.app.schemas.applications import (
    AnswerEdit,
    PacketEdit,
    QuestionInput,
    ReviewInput,
    RevisionInput,
)
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationInvalid,
)
from backend.app.services.applications.review import ApplicationReview
from backend.tests.phase5a_fakes import approve, create

pytestmark = pytest.mark.asyncio


async def test_revision_specific_approval_and_unreviewed_narrative(
    packet_service, application_target
):
    job, _ = application_target
    packet = await create(
        packet_service, job, questions=[QuestionInput(question="Describe a project")]
    )
    packet = await packet_service.generate(
        packet.id, packet.fields[-1].id, RevisionInput(expected_revision=1)
    )
    await packet_service.session.commit()
    review = ApplicationReview(packet_service)
    with pytest.raises(ApplicationConflict, match="Review answer"):
        await review.review(
            packet.id,
            ReviewInput(
                expected_revision=packet.revision,
                action="approve",
                confirm_resume=True,
                confirm_destination=True,
            ),
        )
    packet = await approve(packet_service, packet)
    assert packet.approved_revision == packet.revision == 3
    assert (
        packet.lifecycle_state == "approved_for_manual_handoff"
        and packet.review_status == "approved"
    )
    assert job.status == "discovered"
    with pytest.raises(ApplicationConflict, match="revision"):
        await review.review(
            packet.id, ReviewInput(expected_revision=1, action="approve")
        )


async def test_material_human_edit_requires_rereview(
    packet_service, application_target
):
    job, _ = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    packet = await packet_service.edit_answer(
        packet.id,
        packet.fields[0].id,
        AnswerEdit(expected_revision=packet.revision, answer="Alex Fictional Example"),
    )
    await packet_service.session.commit()
    assert (
        packet.approved_revision is None and packet.fields[0].review_status == "pending"
    )
    assert packet.fields[0].human_answer == "Alex Fictional Example"
    assert packet.fields[0].provenance.source == "human"
    assert packet.snapshot.candidate.full_name == "Alex Example"
    with pytest.raises(ApplicationConflict):
        await ApplicationReview(packet_service).handoff(packet.id)
    packet = await approve(packet_service, packet)
    assert packet.fields[0].effective_answer == "Alex Fictional Example"


@pytest.mark.parametrize(
    "change", ["profile", "resume", "evidence", "job_url", "job_description"]
)
async def test_saved_data_changes_flag_stale_and_block_approval(
    packet_service, application_target, db_session, phase2_profile, change
):
    from backend.app.models.application_answer import CandidateEvidence

    job, resume = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    if change == "profile":
        phase2_profile.phone = "+1 555 0100"
    elif change == "resume":
        resume.user_confirmed = False
    elif change == "evidence":
        db_session.add(
            CandidateEvidence(
                candidate_profile_id=phase2_profile.id,
                title="Example evidence",
                content="I implemented authentication.",
                evidence_type="experience",
                user_confirmed=True,
            )
        )
    elif change == "job_url":
        job.application_url = "https://example.org/new-apply"
    else:
        job.description = "A changed description"
    await db_session.commit()
    result = await packet_service.read(packet.id)
    assert result.review_status == "stale" and result.readiness.stale
    with pytest.raises(ApplicationConflict):
        await ApplicationReview(packet_service).handoff(packet.id)
    with pytest.raises(ApplicationConflict, match="changed"):
        await ApplicationReview(packet_service).review(
            packet.id,
            ReviewInput(
                expected_revision=packet.revision,
                action="approve",
                confirm_resume=True,
                confirm_destination=True,
            ),
        )
    result = await packet_service.edit(
        packet.id,
        PacketEdit(expected_revision=packet.revision, refresh_saved_data=True),
    )
    assert result.approved_revision is None and not result.readiness.stale


@pytest.mark.parametrize(
    "kwargs", [{}, {"confirm_resume": True}, {"confirm_destination": True}]
)
async def test_resume_and_destination_confirmation_required(
    packet_service, application_target, kwargs
):
    packet = await create(packet_service, application_target[0])
    with pytest.raises(ApplicationInvalid, match="confirm"):
        await ApplicationReview(packet_service).review(
            packet.id, ReviewInput(expected_revision=1, action="approve", **kwargs)
        )


async def test_review_rejects_cross_packet_and_missing_field(
    packet_service, application_target
):
    packet = await create(packet_service, application_target[0])
    for ids in [
        [uuid4()],
        [packet.fields[0].id, packet.fields[0].id],
        [packet.fields[2].id],
    ]:
        with pytest.raises(ApplicationInvalid):
            await ApplicationReview(packet_service).review(
                packet.id, ReviewInput(expected_revision=1, reviewed_field_ids=ids)
            )


async def test_no_fake_upload_attestation(packet_service, application_target):
    packet = await create(packet_service, application_target[0])
    with pytest.raises(ApplicationInvalid, match="upload"):
        await packet_service.edit_answer(
            packet.id,
            packet.fields[-1].id,
            AnswerEdit(expected_revision=1, answer="File uploaded"),
        )


@pytest.mark.parametrize(
    "kwargs,answer",
    [
        ({"max_characters": 10}, "An answer longer than ten characters"),
        ({"max_words": 2}, "This has four words"),
        ({"field_type": "url"}, "http://localhost/private"),
        ({"field_type": "yes_no", "options": ["Yes", "No"]}, "Maybe"),
    ],
)
async def test_human_edit_constraints(
    packet_service, application_target, kwargs, answer
):
    packet = await create(
        packet_service,
        application_target[0],
        questions=[QuestionInput(question="Custom application question", **kwargs)],
    )
    with pytest.raises(ApplicationInvalid):
        await packet_service.edit_answer(
            packet.id,
            packet.fields[-1].id,
            AnswerEdit(expected_revision=1, answer=answer),
        )
