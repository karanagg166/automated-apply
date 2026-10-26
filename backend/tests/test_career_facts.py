"""Protected structured facts, exact units, unknowns and conservative authorization scope."""

import pytest
from pydantic import ValidationError

from backend.app.ai.schemas import GenerateRequest
from backend.app.repositories.candidate_profile import CandidateProfileRepository
from backend.app.schemas.candidate_profile import (
    CandidateProfileUpdate,
    CompensationFact,
)
from backend.app.services.application_answer_service import ApplicationAnswerService


@pytest.mark.asyncio
async def test_approved_compensation_is_distinct_from_minimum_and_never_uses_model(
    db_session, phase2_profile
):
    await CandidateProfileRepository(db_session).update_primary_profile(
        CandidateProfileUpdate(
            preferences={
                "current_compensation": {
                    "amount": "1200000",
                    "currency": "INR",
                    "period": "year",
                    "kind": "ctc",
                },
                "expected_compensation": {
                    "amount": "1800000",
                    "currency": "INR",
                    "period": "year",
                    "kind": "ctc",
                },
                "minimum_salary": 900000,
                "salary_currency": "INR",
            }
        ),
        phase2_profile.version,
    )
    await db_session.commit()

    class NeverModel:
        async def generate_structured_answer(self, *args):
            raise AssertionError("Factual questions cannot use a model")

    service = ApplicationAnswerService(db_session, provider=NeverModel())
    for question, expected in [
        ("What is your current CTC?", "1200000 INR per year (ctc)"),
        ("Expected CTC in LPA", "18"),
        ("Current salary", None),
        ("Current monthly CTC", None),
        ("Expected CTC in USD", None),
        ("Current and expected CTC", None),
        ("What is your notice period and current CTC?", None),
    ]:
        result = await service.generate(GenerateRequest(question=question))
        assert result.answer == expected
        assert not result.used_llm


@pytest.mark.asyncio
async def test_availability_relocation_and_country_authorization_preserve_unknowns(
    db_session, phase2_profile
):
    repo = CandidateProfileRepository(db_session)
    await repo.update_primary_profile(
        CandidateProfileUpdate(
            preferences={
                "availability_date": "2050-02-01",
                "current_location": "Pune",
                "open_to_relocation": False,
                "work_authorizations": [
                    {
                        "country_code": "IN",
                        "country_name": "India",
                        "authorized_to_work": True,
                        "requires_sponsorship_now_or_future": None,
                    }
                ],
            }
        ),
        phase2_profile.version,
    )
    await db_session.commit()
    service = ApplicationAnswerService(db_session)
    for question, expected in [
        ("When can you start?", "2050-02-01"),
        ("Current location", "Pune"),
        ("Are you open to relocation?", "No"),
        ("Are you willing to relocate to London?", None),
        ("Are you legally authorized to work in India?", "Yes"),
        ("Are you legally authorized to work in India or US?", None),
        ("Are you NOT authorized to work in India?", None),
        ("Are you eligible to work in India?", "Yes"),
        ("Do you require sponsorship to work in India?", None),
        ("Are you authorized to work in US?", None),
    ]:
        result = await service.generate(GenerateRequest(question=question))
        assert result.answer == expected, question
        assert not result.used_llm


@pytest.mark.parametrize(
    "values",
    [
        {"amount": "NaN", "currency": "INR", "period": "year", "kind": "ctc"},
        {"amount": 100, "currency": "INR", "kind": "ctc"},
        {"amount": -1, "currency": "USD", "period": "year", "kind": "ctc"},
    ],
)
def test_incomplete_or_invalid_compensation_is_not_a_fact(values):
    with pytest.raises(ValidationError):
        CompensationFact(**values)
