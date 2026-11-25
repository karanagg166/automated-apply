"""Expanded deterministic screening facts (CTC, notice, location, relocation, skill_years)."""

import pytest

from backend.app.browser_v2.answers import CandidateFacts, resolve_answer

PROFILE = {
    "verified_experience_years": 2,
    "verified_skills": ["Python", "React"],
    "preferences": {
        "current_ctc": 6, "expected_ctc": 10, "min_ctc": 9, "notice_period_days": 30,
        "current_location": "Bengaluru", "willing_to_relocate": False, "total_experience_years": 2.5,
        "skill_years": {"Python": 2, "TypeScript": 1.5, "PostgreSQL": 2},
    },
}
FACTS = CandidateFacts.from_profile(PROFILE)
YES_NO = ("Yes", "No")


@pytest.mark.parametrize("question,options,expected", [
    ("What is your current CTC?", (), "6 LPA"),
    ("What is your current CTC in Lakhs?", (), "6"),
    ("Expected CTC (in INR)?", (), "1000000"),
    ("What is your expected CTC?", ("0-5 Lakhs", "5-9 Lakhs", "10+ Lakhs"), "10+ Lakhs"),
    ("Current CTC", ("Below 5,00,000", "5,00,000 - 8,00,000", "Above 8,00,000"), "5,00,000 - 8,00,000"),
    ("What is your notice period?", ("15 Days or less", "1 Month", "2 Months"), "1 Month"),
    ("Can you join within 30 days?", YES_NO, "Yes"),
    ("Can you join within 2 weeks?", YES_NO, "No"),
    ("Are you an immediate joiner?", YES_NO, "No"),
    ("Where are you currently located?", (), "Bengaluru"),
    ("Are you currently located in Bangalore?", YES_NO, "Yes"),
    ("Are you based in Pune?", YES_NO, "No"),
    ("Are you willing to relocate to Pune?", YES_NO, "No"),
    ("Are you willing to relocate to Bangalore?", YES_NO, "Yes"),  # already lives there
    ("How many years of experience do you have in TypeScript?", (), "1.5"),
    ("How many years of experience do you have with PostgreSQL?", ("0-1", "1-3", "3+"), "1-3"),
    ("Do you have experience with TypeScript?", YES_NO, "Yes"),  # from skill_years
    ("What is your total experience?", (), "2.5"),  # total_experience_years wins
])
def test_deterministic_screening_answers(question, options, expected):
    assert resolve_answer(question, options, FACTS) == expected


@pytest.mark.parametrize("question", [
    "Expected CTC per month?",  # unit we do not store: never guess
    "How many years of experience do you have in Kotlin?",
    "Why do you want to join us?",
    "Enter the OTP sent to your phone",
    "What is your PAN card number?",
])
def test_unknown_or_sensitive_questions_return_none_for_hitl(question):
    assert resolve_answer(question, (), FACTS) is None


def test_expected_ctc_is_never_derived_from_min_ctc():
    facts = CandidateFacts.from_profile({"preferences": {"min_ctc": 9}})
    assert resolve_answer("What is your expected CTC?", (), facts) is None


def test_relocation_unknown_without_stored_fact():
    facts = CandidateFacts.from_profile({"preferences": {"current_location": "Delhi"}})
    assert resolve_answer("Are you willing to relocate to Pune?", YES_NO, facts) is None
    assert resolve_answer("Are you willing to relocate to New Delhi?", YES_NO, facts) == "Yes"


def test_total_experience_falls_back_to_verified_profile():
    facts = CandidateFacts.from_profile({"verified_experience_years": 3, "preferences": {}})
    assert facts.experience_years == 3


def test_malformed_skill_years_are_ignored():
    facts = CandidateFacts.from_profile({"preferences": {"skill_years": {"Go": "lots", "Rust": 1}}})
    assert facts.skill_years == {"rust": 1.0}


def test_yes_no_only_answers_no_for_a_recognizable_technology():
    """Non-skill yes/no questions fall through to the cache/LLM/human instead of a fabricated "No"."""
    facts = CandidateFacts(skills=("Python",))
    assert resolve_answer("Do you have experience with Kubernetes?", YES_NO, facts) == "No"
    assert resolve_answer("Are you familiar with k8s?", YES_NO, facts) == "No"
    assert resolve_answer("Do you have experience with Python?", YES_NO, facts) == "Yes"
    assert resolve_answer("Are you comfortable with on-call rotations?", YES_NO, facts) is None
    assert resolve_answer("Are you comfortable working in night shifts?", YES_NO, facts) is None
