"""Phase 9 go-live: education answers from candidate_profiles.education (never invented)."""

from __future__ import annotations

from backend.app.browser_v2.answers import CandidateFacts, resolve_answer
from backend.app.browser_v2.answers.education import (
    Education,
    education_answer,
    education_from_profile,
)

PROFILE = {"education": [{"institution": "IIITDM Jabalpur", "qualification": "B.Tech",
                          "field_of_study": "Computer Science and Engineering", "graduation_year": "2026"}],
           "preferences": {}}
EDU = education_from_profile(PROFILE)


def test_profile_mapping() -> None:
    assert EDU == Education("IIITDM Jabalpur", "B.Tech", "Computer Science and Engineering", "2026")
    assert education_from_profile({"education": []}) is None and education_from_profile({}) is None


def test_free_text_and_options() -> None:
    assert education_answer("School*", (), EDU) == (True, "IIITDM Jabalpur")
    assert education_answer("School", ("Harvard University", "Other"), EDU) == (True, "Other")
    assert education_answer("School", ("IIITDM Jabalpur", "Other"), EDU) == (True, "IIITDM Jabalpur")
    assert education_answer("University", ("Harvard University",), EDU) == (True, None)  # never guess a school
    degrees = ("High School", "Associate's Degree", "Bachelor's Degree", "Master's Degree", "Other")
    assert education_answer("Degree", degrees, EDU) == (True, "Bachelor's Degree")
    disciplines = ("Biology", "Computer Science", "Electrical Engineering", "Other")
    assert education_answer("Discipline", disciplines, EDU) == (True, "Computer Science")
    assert education_answer("Graduation year", ("2025", "2026", "2027"), EDU) == (True, "2026")
    assert education_answer("End date year", (), EDU) == (True, "2026")
    assert education_answer("Why do you want to work here?", (), EDU) == (False, None)


def test_resolver_uses_education() -> None:
    facts = CandidateFacts.from_profile(PROFILE)
    assert resolve_answer("School", (), facts) == "IIITDM Jabalpur"
    assert resolve_answer("Degree", ("Bachelor's Degree", "Master's Degree"), facts) == "Bachelor's Degree"
    assert CandidateFacts.from_profile({"preferences": {}}).education is None


def test_previous_employer_phrasings() -> None:
    facts = CandidateFacts.from_profile({"preferences": {"current_company": "Acme Labs"}})
    for question in ("Who is your current or previous employer?", "Most recent employer", "Previous employer",
                     "Current company", "Latest company name"):
        assert resolve_answer(question, (), facts) == "Acme Labs", question
    assert resolve_answer("Why do you want to join our company?", (), facts) is None


def test_current_title_phrasings() -> None:
    facts = CandidateFacts.from_profile({"preferences": {"current_title": "Software Engineer"}})
    for question in ("What is your current or previous job title?", "Current job title", "Most recent title",
                     "Current designation", "Previous role"):
        assert resolve_answer(question, (), facts) == "Software Engineer", question
    assert resolve_answer("Job title you are applying for", (), facts) is None


def test_hear_about_answers() -> None:
    facts = CandidateFacts.from_profile({"preferences": {}})
    assert resolve_answer("How did you hear about Twilio?", ("Careers Website", "LinkedIn", "Twitter"), facts) \
        == "Careers Website"
    assert resolve_answer("How did you hear about us?", ("Referral", "Online job board", "Other"), facts) \
        == "Online job board"
    assert resolve_answer("Where did you hear about this role?", ("Referral", "Other (please specify)"), facts) \
        == "Other (please specify)"
    assert resolve_answer("How did you hear about us?", (), facts) == "Company careers page"
    assert resolve_answer("How did you hear about us?", ("Referral", "Event"), facts) is None
