"""Previous reviewed answers and resume references survive edits in private storage."""

import pytest

from backend.app.dashboard.models import OwnerPreference
from backend.app.repositories.application_packet import revision_archive_key
from backend.app.schemas.applications import AnswerEdit, QuestionInput, ReviewInput
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.review import ApplicationReview
from backend.tests.phase5a_fakes import create


@pytest.mark.asyncio
async def test_reviewed_human_answer_and_resume_are_archived_before_replacement(
    db_session, packet_service, application_target
):
    packet = await create(
        packet_service,
        application_target[0],
        questions=[QuestionInput(question="Describe a project")],
    )
    field_id = packet.fields[-1].id
    packet = await packet_service.edit_answer(
        packet.id,
        field_id,
        AnswerEdit(
            expected_revision=packet.revision, answer="I built a fictional API."
        ),
    )
    packet = await ApplicationReview(packet_service).review(
        packet.id,
        ReviewInput(
            expected_revision=packet.revision,
            action="review",
            reviewed_field_ids=[field_id],
        ),
    )
    await db_session.commit()
    revision, resume = packet.revision, packet.snapshot.resume.model_dump(mode="json")
    packet = await packet_service.edit_answer(
        packet.id,
        field_id,
        AnswerEdit(
            expected_revision=packet.revision,
            answer="I reviewed my actual API contribution.",
        ),
    )
    await db_session.commit()
    archive = await db_session.get(
        OwnerPreference, revision_archive_key(packet.id, revision)
    )
    assert archive is not None
    assert archive.value["snapshot"]["resume"] == resume
    old = next(f for f in archive.value["fields"] if f["id"] == str(field_id))
    assert (
        old["human_answer"] == "I built a fictional API."
        and old["review_status"] == "reviewed"
    )
    assert archive.value["digest"] == digest(
        {k: v for k, v in archive.value.items() if k != "digest"}
    )
    assert packet.fields[-1].review_status == "pending"
