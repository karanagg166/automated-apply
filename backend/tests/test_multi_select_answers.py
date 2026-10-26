"""Exact sets, unknown facts and zero-provider deterministic proposals."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.applications import QuestionInput
from backend.app.services.applications.answer_builder import AnswerBuilder, value_error
from backend.app.services.applications.multi_select import decode, encode


@pytest.mark.parametrize(
    "answer",
    [
        '"Python"',
        "{}",
        "[1]",
        "[true]",
        "[null]",
        "[[]]",
        '["Go"]',
        '["python"]',
        '["Python","Python"]',
        "[]",
        "not json",
    ],
)
def test_multiple_answer_rejects_nonsets_unknown_options_duplicates_and_missing_required(
    answer,
):
    with pytest.raises(ValueError):
        decode(answer, ["Python", "FastAPI"], required=True)


def test_optional_empty_set_and_labels_with_commas_or_quotes_are_explicit():
    labels = ["Python, FastAPI", 'Project "Relay"']
    assert decode(encode(labels), labels, required=True) == labels
    assert decode("[]", labels, required=False) == []
    assert decode(encode(['Project "Relay"']), labels, required=True) == [
        'Project "Relay"'
    ]


@pytest.mark.parametrize("options", [[], ["Python", "python"], [" "]])
def test_multiple_question_requires_actual_unique_nonblank_options(options):
    with pytest.raises(ValidationError):
        QuestionInput(
            question="Technical skills", field_type="multi_select", options=options
        )


class NoModel:
    async def generate(self, request):
        raise AssertionError("Multiple facts must not invoke a model")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Technical skills",
        "Which technical skills do you have?",
        "Technical skills (select all that apply) *",
    ],
)
async def test_verified_skills_propose_only_exact_known_options_and_require_review(
    question,
):
    field = await AnswerBuilder(NoModel()).build(
        QuestionInput(
            question=question,
            field_type="multi_select",
            options=["Go", "FastAPI", "Python"],
        ),
        uuid4(),
        SimpleNamespace(id=uuid4(), verified_skills=["Python", "FastAPI"]),
        generate=True,
    )
    assert json.loads(field.effective_answer) == ["FastAPI", "Python"]
    assert field.requires_review and field.review_status == "pending"
    assert (
        field.provenance.source == "candidate_profile"
        and field.provenance.evidence_references
    )
    assert (
        value_error(field, '["Go"]') is None
    )  # Only an explicit human may supply this choice.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Languages with 5 years of production experience",
        "Expert technical skills",
        "Certifications",
        "Preferred cities",
        "Resume formats",
    ],
)
async def test_unknown_or_more_qualified_claims_never_inherit_plain_skill_facts(
    question,
):
    field = await AnswerBuilder(NoModel()).build(
        QuestionInput(
            question=question, field_type="multi_select", options=["Python", "FastAPI"]
        ),
        uuid4(),
        SimpleNamespace(id=uuid4(), verified_skills=["Python", "FastAPI"]),
        generate=True,
    )
    assert field.effective_answer is None and field.validation_status == "needs_input"
    assert field.requires_review
