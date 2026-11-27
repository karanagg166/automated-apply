"""Owner-declared screening disclosures (EEO / consent / NDA) answered in tier 0.

Real Greenhouse / Lever EEO phrasings and option lists. Every identity here is synthetic.
"""

import json
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.pii import profile_secrets
from backend.app.ai_v2.screening import KIND, ScreeningAnswerer
from backend.app.ai_v2.semantic_cache import MemoryCacheStore, SemanticCache
from backend.app.browser_v2 import facts_cli
from backend.app.browser_v2.answers import (
    CandidateFacts,
    disclosure_answer,
    resolve_answer,
)
from backend.app.browser_v2.answers.facts import DISCLOSURE_KEYS
from backend.app.browser_v2.store import MemoryStore
from backend.app.schemas.candidate_profile import (
    JobSearchPreferences,
    JobSearchPreferencesUpdate,
    ScreeningDisclosures,
)

YES_NO = ("Yes", "No")
SIGNATURE = "Test Candidate Person"
DISCLOSURES = {
    "gender": "Male", "ethnicity": "Asian (Indian)", "veteran_status": "I am not a protected veteran",
    "disability_status": "No, I do not have a disability", "pronouns": "He/Him",
    "date_of_birth": "2003-05-14", "citizenship": "India", "has_valid_passport": True,
    "consent_background_check": True, "consent_data_processing": True, "agree_terms": True,
    "nda_auto_sign": True, "nda_signature_name": SIGNATURE, "currently_employed": False,
}
WORK_AUTH = [{"country_code": "IN", "country_name": "India", "authorized_to_work": True,
              "requires_sponsorship_now_or_future": False},
             {"country_code": "US", "country_name": "United States", "authorized_to_work": False,
              "requires_sponsorship_now_or_future": True}]
PROFILE = {"full_name": SIGNATURE, "email": "test.candidate@example.com",
           "preferences": {"screening_disclosures": DISCLOSURES, "work_authorizations": WORK_AUTH}}
FACTS = CandidateFacts.from_profile(PROFILE)
BARE = CandidateFacts.from_profile({"preferences": {"work_authorizations": WORK_AUTH}})

GH_RACE = ("American Indian or Alaska Native (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)",
           "Black or African American (Not Hispanic or Latino)", "Hispanic or Latino",
           "Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)",
           "Two or More Races (Not Hispanic or Latino)", "White (Not Hispanic or Latino)",
           "Decline To Self Identify")
GH_HISPANIC = ("Yes", "No", "Decline To Self Identify")
GH_GENDER = ("Male", "Female", "Decline To Self Identify")
GH_VETERAN = ("I am a veteran", "I identify as one or more of the classifications of protected veteran",
              "I am not a protected veteran", "I don't wish to answer")
LEVER_VETERAN = ("I am a protected veteran", "I am not a protected veteran", "Decline to self-identify")
GH_DISABILITY = ("Yes, I have a disability, or have had one in the past",
                 "No, I do not have a disability and have not had one in the past", "I do not want to answer")
NDA = "Please Review the NDA and indicate your agreement by typing your full name below"


def _facts(**overrides):
    return CandidateFacts.from_profile({"preferences": {"screening_disclosures": {**DISCLOSURES, **overrides}}})


# --- schema ----------------------------------------------------------------------------------
def test_schema_accepts_the_owner_shape_and_rejects_loose_values():
    prefs = JobSearchPreferences(screening_disclosures=DISCLOSURES)
    assert prefs.screening_disclosures.date_of_birth == date(2003, 5, 14)
    assert prefs.screening_disclosures.nda_signature_name == SIGNATURE
    assert JobSearchPreferencesUpdate(screening_disclosures={"gender": "Female"}).screening_disclosures.gender == "Female"
    assert JobSearchPreferences().screening_disclosures is None
    for bad in ({"agree_terms": "yes"}, {"sexual_orientation": "x"}, {"gender": "x" * 121}, {"gender": "  "},
                {"nda_auto_sign": True}, {"date_of_birth": (date.today() + timedelta(days=1)).isoformat()}):
        with pytest.raises(ValidationError):
            ScreeningDisclosures(**bad)


def test_facts_load_only_explicitly_stored_well_typed_values():
    assert FACTS.disclosures["date_of_birth"] == date(2003, 5, 14)
    assert FACTS.disclosures["has_valid_passport"] is True
    assert BARE.disclosures == {}
    loose = CandidateFacts.from_profile({"preferences": {"screening_disclosures": {
        "agree_terms": "yes", "gender": "  ", "date_of_birth": "not-a-date", "pronouns": " she/her "}}})
    assert loose.disclosures == {"pronouns": "she/her"}


# --- answers ---------------------------------------------------------------------------------
@pytest.mark.parametrize("question,options,expected", [
    ("Please identify your race", GH_RACE, "Asian (Not Hispanic or Latino)"),
    ("Race/Ethnicity", GH_RACE, "Asian (Not Hispanic or Latino)"),
    ("Are you Hispanic/Latino?", GH_HISPANIC, "No"),
    ("Gender", GH_GENDER, "Male"),
    ("What is your gender identity?", ("Man", "Woman", "Non-binary", "Prefer not to say"), "Man"),
    ("Veteran Status", GH_VETERAN, "I am not a protected veteran"),
    ("Are you a protected veteran?", LEVER_VETERAN, "I am not a protected veteran"),
    ("Disability Status", GH_DISABILITY, "No, I do not have a disability and have not had one in the past"),
    ("Do you have a disability?", YES_NO, "No"),
    ("What are your pronouns?", (), "He/Him"),
    ("Pronouns", ("He/Him/His", "She/Her/Hers", "They/Them/Theirs"), "He/Him/His"),
    ("Date of Birth", (), "2003-05-14"),
    ("Date of birth (DD/MM/YYYY)", (), "14/05/2003"),
    ("DOB (mm-dd-yyyy)", (), "05-14-2003"),
    ("What is your nationality?", ("Indian", "Other"), "Indian"),
    ("Country of citizenship", ("United States", "India", "Other"), "India"),
    ("Citizenship", (), "India"),
    ("Are you a U.S. citizen?", YES_NO, "No"),
    ("Are you a citizen of India?", YES_NO, "Yes"),
    ("Do you have a valid passport?", YES_NO, "Yes"),
    ("Do you consent to a background check?", YES_NO, "Yes"),
    ("Are you willing to undergo a background verification?", YES_NO, "Yes"),
    ("I agree to the Terms and Conditions", YES_NO, "Yes"),
    ("I have read and agree to the Privacy Policy and consent to the processing of my personal data",
     YES_NO, "Yes"),
    ("By checking this box, I acknowledge the Candidate Privacy Notice", ("I acknowledge",), "I acknowledge"),
    (NDA, (), SIGNATURE),
    ("I agree to the NDA", YES_NO, "Yes"),
    ("Are you currently employed?", YES_NO, "No"),
    ("Employment status", ("Employed", "Unemployed", "Student"), "Unemployed"),
])
def test_declared_disclosures_fill_greenhouse_and_lever_questions(question, options, expected):
    assert resolve_answer(question, options, FACTS) == expected
    assert resolve_answer(question, options, BARE) is None  # missing fact -> human, never fabricated


@pytest.mark.parametrize("question,options", [
    ("Password", ()), ("Create a password", ()), ("Enter the OTP sent to your phone", ()),
    ("Verification code", ()), ("Aadhaar number", ()), ("PAN card number", ()),
    ("Bank account number", ()), ("Social Security Number", ()), ("Email", ()), ("Login ID", ()),
    ("What is your sexual orientation?", ("Heterosexual", "Gay", "Bisexual", "Decline To Self Identify")),
    ("Gender identity and sexual orientation", ()), ("What is your religion?", ()),
    ("Legal declaration: I agree to the terms", YES_NO),
    ("I hereby declare that the information provided is true", YES_NO),
    ("Passport number", ()), ("Do you consent to receive SMS updates about your application?", YES_NO),
    ("I agree to receive marketing emails", YES_NO), ("Do you consent to us contacting your references?", YES_NO),
    ("Have you signed an NDA with your current employer?", YES_NO),
])
def test_other_sensitive_and_blocked_questions_stay_with_the_human(question, options):
    assert disclosure_answer(question, options, FACTS) == (False, None)
    assert resolve_answer(question, options, FACTS) is None


@pytest.mark.parametrize("question,options", [
    ("Will you now or in the future require sponsorship for employment visa status?", YES_NO),
    ("Are you legally authorized to work in the United States?", YES_NO),
    ("Have you ever failed a background check?", YES_NO),
    ("Do you agree to work under the terms of employment described above?", YES_NO),
    ("Have you debugged a race condition before?", YES_NO),
    ("Do you need any accommodation for a disability during the interview?", YES_NO),
])
def test_neighbouring_questions_are_untouched(question, options):
    assert disclosure_answer(question, options, FACTS) == (False, None)
    assert resolve_answer(question, options, FACTS) == resolve_answer(question, options, BARE)


def test_sponsorship_still_comes_from_work_authorizations():
    question = "Will you now or in the future require sponsorship to work in the United States?"
    assert resolve_answer(question, YES_NO, FACTS) == "Yes"


def test_no_safe_option_goes_to_the_human():
    ambiguous = ("East Asian", "South Asian", "Southeast Asian", "Prefer not to say")
    assert disclosure_answer("Ethnicity", ambiguous, FACTS) == (True, None)
    assert resolve_answer("Ethnicity", ambiguous, FACTS) is None
    assert resolve_answer("Do you hold dual citizenship?", YES_NO, FACTS) is None
    assert resolve_answer("Date of birth", ("1990", "2000"), FACTS) is None
    assert resolve_answer("Veteran status", ("Veteran", "Disabled veteran", "Other protected veteran"),
                          _facts(veteran_status="I am a protected veteran")) is None


def test_declined_and_negative_facts_are_answered_truthfully():
    declined = _facts(ethnicity="Decline to self-identify", gender="Prefer not to say")
    assert resolve_answer("Please identify your race", GH_RACE, declined) == "Decline To Self Identify"
    assert resolve_answer("Are you Hispanic/Latino?", GH_HISPANIC, declined) == "Decline To Self Identify"
    assert resolve_answer("Gender", GH_GENDER, declined) == "Decline To Self Identify"
    no_terms = _facts(agree_terms=False)
    assert resolve_answer("I agree to the Terms and Conditions", YES_NO, no_terms) == "No"
    assert resolve_answer("I agree to the Terms and Privacy Policy", YES_NO, no_terms) == "No"
    missing = {k: v for k, v in DISCLOSURES.items() if k != "consent_data_processing"}
    partial = CandidateFacts.from_profile({"preferences": {"screening_disclosures": missing}})
    assert resolve_answer("I agree to the Terms and Privacy Policy", YES_NO, partial) is None


def test_nda_signature_only_when_auto_sign_is_on():
    assert resolve_answer(NDA, (), _facts(nda_auto_sign=False)) is None
    unsigned = {k: v for k, v in DISCLOSURES.items() if k not in ("nda_auto_sign", "nda_signature_name")}
    assert resolve_answer(NDA, (), CandidateFacts.from_profile(
        {"preferences": {"screening_disclosures": unsigned}})) is None
    assert resolve_answer("Have you read the NDA?", (), FACTS) is None


# --- tier pipeline: tier 0 before the gate, never cached, never an LLM ------------------------
class _SpyRouter:
    any_configured = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("a disclosure question must never reach the LLM")


async def test_screening_answers_disclosures_in_tier_zero_without_cache_or_llm():
    cache = SemanticCache(MemoryCacheStore(), DeterministicTestEmbedder())
    router = _SpyRouter()
    answerer = ScreeningAnswerer(cache, router)  # type: ignore[arg-type]
    hit = await answerer.resolve("Veteran Status", GH_VETERAN, FACTS)
    assert (hit.tier, hit.source, hit.reason, hit.answer) == (0, "profile", "owner_disclosure",
                                                              "I am not a protected veteran")
    signed = await answerer.resolve(NDA, (), FACTS)
    assert (signed.tier, signed.answer) == (0, SIGNATURE)
    unsafe = await answerer.resolve("Ethnicity", ("East Asian", "South Asian"), FACTS)
    assert (unsafe.tier, unsafe.answer, unsafe.reason) == (3, None, "disclosure_no_safe_option")
    missing = await answerer.resolve("Veteran Status", GH_VETERAN, BARE)
    assert (missing.tier, missing.reason) == (3, "sensitive_or_blocked_question")
    unsigned = await answerer.resolve(NDA, (), BARE)
    assert (unsigned.tier, unsigned.reason) == (3, "sensitive_or_blocked_question")
    assert router.calls == 0
    for question in ("Veteran Status", NDA, "Ethnicity"):
        assert await cache.lookup(KIND, question) is None


async def test_facts_report_lists_disclosure_keys_masked():
    store = MemoryStore(profile=json.loads(json.dumps(PROFILE)))
    report = await facts_cli.facts_report(store)
    assert {f"disclosures.{key}" for key in DISCLOSURE_KEYS} <= set(report["present"])
    assert report["masked"]["disclosures.nda_auto_sign"] == "yes"
    dumped = json.dumps(report["masked"])
    for secret in ("Asian", "2003", "Candidate", "protected", "He/Him"):
        assert secret not in dumped
    empty = await facts_cli.facts_report(MemoryStore(profile={"preferences": {}}))
    assert "disclosures.gender" in empty["missing"]


def test_nda_signature_name_is_scrubbed_from_llm_prompts():
    other = {"preferences": {"screening_disclosures": {"nda_auto_sign": True, "nda_signature_name": "Other Legal Name"}}}
    assert "Other Legal Name" in profile_secrets(other)
