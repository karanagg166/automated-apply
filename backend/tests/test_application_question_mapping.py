"""Facts and narrative requests use the original answer engine without invention."""

import pytest
from sqlalchemy import select

from backend.app.models.application_answer import ApplicationAnswerDraft
from backend.app.schemas.applications import CreatePacket, QuestionInput, RevisionInput
from backend.tests.phase5a_fakes import create

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "question,value",
    [
        ("Full name", "Alex Example"),
        ("Email", "alex@example.com"),
        ("Phone number", None),
        ("GitHub profile URL", "https://github.com/example"),
        ("LinkedIn profile URL", "https://www.linkedin.com/in/example"),
        ("What is your education?", None),
        ("Work authorization status?", None),
        ("Are you authorized to work in Example Country?", None),
        ("What is your expected salary?", None),
        ("Current salary?", None),
        ("Notice period?", "30 days"),
        ("What technologies have you used?", "Python, FastAPI"),
        ("What is your age?", None),
        ("What is your gender?", None),
    ],
)
async def test_saved_facts_or_explicit_missing(
    packet_service, application_target, question, value
):
    job, _ = application_target
    preview = await packet_service.preview(
        job.id,
        CreatePacket(
            idempotency_key="fictional-mapping",
            questions=[QuestionInput(question=question)],
        ),
    )
    field = preview.fields[-1]
    assert field.effective_answer == value
    assert not packet_service.builder.answers.answer_service.provider.calls
    if value is None:
        assert field.validation_status == "needs_input" and field.missing_information


async def test_choice_requires_exact_saved_value(packet_service, application_target):
    job, _ = application_target
    result = await packet_service.preview(
        job.id,
        CreatePacket(
            idempotency_key="fictional-choice",
            questions=[
                QuestionInput(
                    question="Notice period",
                    field_type="multiple_choice",
                    options=["Immediate", "30", "60"],
                ),
                QuestionInput(
                    question="Notice period",
                    field_type="multiple_choice",
                    options=["30 days", "60 days"],
                ),
            ],
        ),
    )
    assert (
        result.fields[-2].effective_answer is None
        and result.fields[-2].validation_status == "validation_failed"
    )
    assert result.fields[-1].effective_answer == "30 days"


async def test_narrative_is_explicit_grounded_and_saves_existing_answer_draft(
    packet_service, application_target, db_session
):
    job, _ = application_target
    packet = await create(
        packet_service,
        job,
        questions=[
            QuestionInput(
                question="Describe your most technically challenging project",
                field_type="textarea",
                writing_style="technical",
            )
        ],
    )
    field = packet.fields[-1]
    assert (
        field.proposed_answer is None
        and not packet_service.builder.answers.answer_service.provider.calls
    )
    packet = await packet_service.generate(
        packet.id, field.id, RevisionInput(expected_revision=packet.revision)
    )
    field = packet.fields[-1]
    assert (
        field.validation_status == "draft_ready"
        and "Concurrent connections" in field.proposed_answer
    )
    assert "checked authentication" in field.proposed_answer
    assert field.requires_review and field.review_status == "pending"
    assert field.provenance.source == "gemini" and field.provenance.evidence_references
    draft = await db_session.get(
        ApplicationAnswerDraft, field.provenance.answer_draft_id
    )
    assert draft.answer == field.proposed_answer and draft.review_status == "draft"
    assert len(packet_service.builder.answers.answer_service.provider.calls) == 1
    assert (await db_session.scalars(select(ApplicationAnswerDraft))).all()


@pytest.mark.parametrize(
    "answer", ["I worked at InventedCorp.", "I supported 100000 users."]
)
async def test_invalid_claim_never_becomes_copyable(
    packet_service, application_target, answer
):
    job, _ = application_target
    packet_service.builder.answers.answer_service.provider.answer = answer
    packet = await create(
        packet_service, job, questions=[QuestionInput(question="Describe a project")]
    )
    packet = await packet_service.generate(
        packet.id, packet.fields[-1].id, RevisionInput(expected_revision=1)
    )
    assert packet.fields[-1].validation_status == "validation_failed"
    assert packet.fields[-1].effective_answer is None


@pytest.mark.parametrize("limits", [{"max_characters": 20}, {"max_words": 3}])
async def test_generation_respects_limits_without_truncation(
    packet_service, application_target, limits
):
    job, _ = application_target
    packet = await create(
        packet_service,
        job,
        questions=[QuestionInput(question="Describe a project", **limits)],
    )
    packet = await packet_service.generate(
        packet.id, packet.fields[-1].id, RevisionInput(expected_revision=1)
    )
    assert (
        packet.fields[-1].validation_status == "validation_failed"
        and packet.fields[-1].effective_answer is None
    )


@pytest.mark.parametrize("kind", ["project", "provider", "company"])
async def test_missing_evidence_or_provider_is_explicit(
    packet_service, application_target, phase2_profile, db_session, kind
):
    job, _ = application_target
    question = "Describe a project"
    if kind == "project":
        phase2_profile.projects = []
    elif kind == "company":
        question = "Why are you interested in this company?"
        job.description = None
    else:
        packet_service.builder.answers.answer_service.settings.GEMINI_API_KEY = None
        packet_service.builder.answers.answer_service.provider = None
    await db_session.commit()
    packet = await create(
        packet_service, job, questions=[QuestionInput(question=question)]
    )
    packet = await packet_service.generate(
        packet.id, packet.fields[-1].id, RevisionInput(expected_revision=1)
    )
    assert packet.fields[-1].validation_status == (
        "provider_unavailable" if kind == "provider" else "needs_input"
    )
    assert packet.fields[-1].effective_answer is None


async def test_missing_career_facts_are_not_inferred_from_projects(
    packet_service, application_target, phase2_profile, db_session
):
    (
        phase2_profile.verified_roles,
        phase2_profile.education,
        phase2_profile.verified_experience_years,
    ) = [], [], None
    await db_session.commit()
    packet = await create(
        packet_service,
        application_target[0],
        questions=[
            QuestionInput(question="Total years of experience?"),
            QuestionInput(question="Education?"),
        ],
    )
    assert all(f.effective_answer is None for f in packet.fields[-2:])
    assert (
        packet.snapshot.candidate.verified_roles == []
        and packet.snapshot.candidate.education == []
    )


async def test_production_issue_uses_confirmed_challenge_evidence(
    packet_service, application_target
):
    packet = await create(
        packet_service,
        application_target[0],
        questions=[QuestionInput(question="Describe a production issue you solved")],
    )
    packet = await packet_service.generate(
        packet.id, packet.fields[-1].id, RevisionInput(expected_revision=1)
    )
    assert (
        packet.fields[-1].validation_status == "draft_ready"
        and packet.fields[-1].provenance.evidence_references
    )
