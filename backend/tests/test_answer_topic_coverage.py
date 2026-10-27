"""Requested facts must survive ranking and length limits; no model or network."""

import pytest

from backend.app.ai.evidence import prepare_evidence
from backend.app.ai.schemas import GenerateRequest
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.phase2a_fakes import FakeProvider


def context(*facts):
    return {
        "evidence": [
            {
                "reference": {"source_type": "candidate_evidence", "source_id": str(i)},
                "facts": fact,
            }
            for i, fact in enumerate(facts)
        ]
    }


def test_length_limits_cannot_drop_a_requested_topic():
    facts = context(
        {"contribution": "I integrated an API.", "notes": "I supported 12 users."}
    )
    result = prepare_evidence(
        "Which API did you integrate and how many users?",
        facts,
        {"max_characters": 25, "max_words": None},
    )
    assert result.error == "output_constraints_unsatisfied" and not result.clauses


def test_ranking_prefers_evidence_covering_the_entire_question():
    facts = context(
        {"name": "API", "contribution": "I integrated an API."},
        {"contribution": "I integrated an API for 12 users."},
    )
    result = prepare_evidence(
        "Which API did you integrate for users?",
        facts,
        {"max_characters": 500, "max_words": 100},
    )
    assert not result.missing and not result.error
    assert result.clauses[0].source.source_id == "1"


@pytest.mark.asyncio
async def test_bug_answer_includes_actual_challenge_and_solution(
    db_session, phase2_profile, phase2_settings
):
    fake = FakeProvider(error=AssertionError("No provider authorized"))
    service = ApplicationAnswerService(db_session, phase2_settings, fake)
    result = await service.generate(
        GenerateRequest(question="What was the hardest bug you fixed?", save_draft=True)
    )
    assert result.status == "draft_ready", result
    assert phase2_profile.projects[0]["engineering_challenges"] in result.answer
    assert phase2_profile.projects[0]["solutions"] in result.answer
    assert result.requires_review and result.evidence_references and not result.used_llm
    assert not fake.calls


@pytest.mark.asyncio
async def test_bug_without_solution_is_manual(
    db_session, phase2_profile, phase2_settings
):
    phase2_profile.projects = [{**phase2_profile.projects[0], "solutions": None}]
    await db_session.commit()
    fake = FakeProvider(error=AssertionError("Missing facts must not call a provider"))
    result = await ApplicationAnswerService(db_session, phase2_settings, fake).generate(
        GenerateRequest(question="What was the hardest bug you fixed?", rewrite=True)
    )
    assert result.status == "needs_input" and result.answer is None and not fake.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_integration", [True, False])
async def test_api_integration_requires_personally_attributable_work(
    db_session, phase2_profile, phase2_settings, approved_integration
):
    contribution = "I integrated the Example API to retrieve fictional task updates."
    if approved_integration:
        phase2_profile.projects = [{**phase2_profile.projects[0], "contribution": contribution}]
        await db_session.commit()
    fake = FakeProvider(error=AssertionError("No model needed for approved API facts"))
    result = await ApplicationAnswerService(db_session, phase2_settings, fake).generate(
        GenerateRequest(question="Which API have you integrated?")
    )
    assert not fake.calls and not result.used_llm
    if approved_integration:
        assert result.answer == contribution and result.evidence_references and result.requires_review
    else:
        assert result.status == "needs_input" and result.answer is None
