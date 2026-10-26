"""Selection retains confirmed resources, not fictitious file uploads."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.schemas.applications import PacketEdit, PrepareInput
from backend.app.services.applications.resume_selector import select_resume
from backend.tests.phase5a_fakes import approve, create


def resource(**kwargs):
    return SimpleNamespace(
        **dict(
            id=uuid4(),
            label="Fictional resume",
            resource_type="resume",
            updated_at="2026-01-01",
            **{
                "url": "https://example.org/resume.pdf",
                "is_primary": True,
                "user_confirmed": True,
                **kwargs,
            },
        )
    )


def test_unique_confirmed_primary():
    item = resource()
    result = select_resume([item])
    assert result.selected.resource_id == item.id
    assert result.upload_status == "manual_resume_upload_required"


def test_private_resume_snapshot_retains_exact_reference_for_postgres_guard():
    resume_id = str(uuid4())
    item = resource(source_type="private_upload", url="private-resume:" + resume_id)
    selected = select_resume([item]).selected
    assert selected.url == item.url
    assert selected.download_path == "/api/backend/dashboard/resumes/" + resume_id


@pytest.mark.parametrize("reference,source", [
    ("private-resume:not-a-uuid", "private_upload"),
    ("private-resume:" + str(uuid4()) + "/../../settings", "private_upload"),
    ("private-resume:" + str(uuid4()), "manual"),
])
def test_private_resume_rejects_invalid_or_untrusted_references(reference, source):
    assert select_resume([resource(url=reference, source_type=source)]).selected is None


@pytest.mark.asyncio
async def test_private_reference_is_not_an_external_resume_url_answer(
    packet_service, application_target, db_session
):
    from backend.app.schemas.applications import QuestionInput

    job, resume = application_target
    resume.url = "private-resume:" + str(uuid4())
    resume.source_type = "private_upload"
    await db_session.commit()
    packet = await create(
        packet_service, job,
        questions=[QuestionInput(question="Resume URL?", field_type="url")],
    )
    assert packet.snapshot.resume.selected.url == resume.url
    assert packet.fields[-1].effective_answer is None
    assert packet.fields[-1].validation_status == "validation_failed"


@pytest.mark.parametrize(
    "resources",
    [
        [],
        [resource(user_confirmed=False)],
        [resource(is_primary=False)],
        [resource(), resource()],
        [resource(url="http://127.0.0.1/resume")],
    ],
)
def test_missing_unconfirmed_or_ambiguous(resources):
    result = select_resume(resources)
    assert result.selected is None and result.reason
    assert len(result.alternatives) == len(resources)


def test_explicit_selection_wins_and_unknown_selection_does_not_fallback():
    primary, alternate = resource(), resource(is_primary=False)
    result = select_resume([primary, alternate], alternate.id)
    assert result.selected.resource_id == alternate.id and "Explicit" in result.reason
    assert select_resume([primary], uuid4()).selected is None


@pytest.mark.asyncio
async def test_selected_resume_change_invalidates_approval(
    packet_service, application_target, db_session, phase2_profile
):
    from backend.app.models.application_answer import CandidateResource

    job, primary = application_target
    alternate = CandidateResource(
        candidate_profile_id=phase2_profile.id,
        resource_type="resume",
        label="Alternate Backend Resume",
        url="https://example.org/alternate.pdf",
        is_primary=False,
        user_confirmed=True,
    )
    db_session.add(alternate)
    await db_session.commit()
    packet = await approve(packet_service, await create(packet_service, job))
    packet = await packet_service.edit(
        packet.id,
        PacketEdit(expected_revision=packet.revision, resume_resource_id=alternate.id),
    )
    assert (
        packet.approved_revision is None
        and packet.snapshot.resume.selected.resource_id == alternate.id
    )
    assert packet.snapshot.resume.selected.resource_id != primary.id
    assert packet.readiness.state == "needs_review"


@pytest.mark.asyncio
async def test_missing_explicit_resume_visible(packet_service, application_target):
    job, _ = application_target
    preview = await packet_service.preview(
        job.id, PrepareInput(resume_resource_id=uuid4())
    )
    assert (
        preview.readiness.state == "needs_resume"
        and preview.snapshot.resume.alternatives
    )


@pytest.mark.asyncio
async def test_resume_link_answer_uses_explicit_packet_selection(
    packet_service, application_target, db_session, phase2_profile
):
    from backend.app.models.application_answer import CandidateResource
    from backend.app.schemas.applications import QuestionInput

    alternate = CandidateResource(
        candidate_profile_id=phase2_profile.id,
        resource_type="resume",
        label="Alternate resume",
        url="https://example.org/selected-resume.pdf",
        is_primary=False,
        user_confirmed=True,
    )
    db_session.add(alternate)
    await db_session.commit()
    packet = await create(
        packet_service,
        application_target[0],
        resume_resource_id=alternate.id,
        questions=[
            QuestionInput(question="What is your resume link?", field_type="url")
        ],
    )
    assert packet.fields[-1].effective_answer == alternate.url
    assert packet.fields[-1].provenance.resource_id == alternate.id


@pytest.mark.asyncio
async def test_resume_removed_after_preparation_blocks_handoff(
    packet_service, application_target, db_session
):
    # SQLite permits this fixture removal; PostgreSQL RESTRICTs selected-resource deletion.
    from backend.app.services.applications.base import ApplicationConflict
    from backend.app.services.applications.review import ApplicationReview

    job, resume = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    await db_session.delete(resume)
    await db_session.commit()
    assert (await packet_service.read(packet.id)).readiness.stale
    with pytest.raises(ApplicationConflict):
        await ApplicationReview(packet_service).handoff(packet.id)
