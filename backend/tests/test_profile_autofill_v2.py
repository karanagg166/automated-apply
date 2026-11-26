"""Workstream 3: common ATS screening questions auto-fill from stored facts; unknowns -> HITL.

All identities are synthetic (example.com / placeholder numbers); no real env is read.
"""

import argparse
import json

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.screening import ScreeningAnswerer
from backend.app.ai_v2.semantic_cache import MemoryCacheStore, SemanticCache
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2 import facts_cli
from backend.app.browser_v2.answers import CandidateFacts, place_facts, resolve_answer
from backend.app.browser_v2.store import MemoryStore

YES_NO = ("Yes", "No")
PHONE = "+91 90000 00000"
PROFILE = {
    "full_name": "Test Candidate Person", "email": "test.candidate@example.com", "phone": PHONE,
    "linkedin_url": "https://www.linkedin.com/in/example-test", "github_url": "https://github.com/example-test",
    "personal_website": "https://example.com", "verified_experience_years": 2,
    "verified_skills": ["Python", "FastAPI"],
    "preferences": {
        "current_location": "Bangalore", "open_to_relocation": True, "notice_period_days": 30,
        "current_ctc": 6, "expected_ctc": 10, "total_experience_years": 2.5, "skill_years": {"python": 2},
        "relocation_locations": ["Pune"], "work_authorization": "Indian citizen",
        "work_authorizations": [{"country_code": "IN", "country_name": "India", "authorized_to_work": True,
                                 "requires_sponsorship_now_or_future": False},
                                {"country_code": "US", "country_name": "United States",
                                 "authorized_to_work": False, "requires_sponsorship_now_or_future": True}],
    },
}
FACTS = CandidateFacts.from_profile(PROFILE)


# --- question -> fact mapping ------------------------------------------------------------
@pytest.mark.parametrize("question,options,expected", [
    # Greenhouse Country combobox (with and without dialing codes), Lever free text
    ("Country", ("Indonesia", "India", "British Indian Ocean Territory"), "India"),
    ("Country", ("British Indian Ocean Territory (+246)", "India (+91)", "Indonesia (+62)"), "India (+91)"),
    ("Country", ("India", "India (+91)"), "India"),
    ("Country of residence", (), "India"),
    ("Which country are you currently based in?", (), "India"),
    ("City", (), "Bangalore"),
    ("State", ("Kerala", "Karnataka", "Maharashtra"), "Karnataka"),
    ("Current location", (), "Bangalore"),
    ("Location", ("Pune, Maharashtra, India", "Bengaluru, Karnataka, India"), "Bengaluru, Karnataka, India"),
    ("Are you currently located in India?", YES_NO, "Yes"),
    ("Are you based in Karnataka?", YES_NO, "Yes"),
    ("Are you located in Pune?", YES_NO, "No"),
    ("Are you located in the United States?", YES_NO, "No"),
    # relocation: open_to_relocation (dashboard key) is the same stored fact
    ("Are you willing to relocate?", YES_NO, "Yes"),
    ("Are you willing to relocate to Pune?", YES_NO, "Yes"),
    # work authorization / sponsorship per stored country rows
    ("Are you legally authorized to work in India?", YES_NO, "Yes"),
    ("Are you authorized to work in the United States?", YES_NO, "No"),
    ("Will you now or in the future require visa sponsorship to work in the USA?", YES_NO, "Yes"),
    ("Work authorization status", (), "Indian citizen"),
    # notice / CTC / experience
    ("When can you start?", (), "Within 30 days"),
    ("Notice period", ("Immediate", "15 days", "30 days", "60 days"), "30 days"),
    ("Current annual CTC (in Lakhs)", (), "6"),
    ("What are your salary expectations?", (), "10 LPA"),
    ("Years of experience", ("0-1 years", "1-2 years", "2-3 years", "3-5 years", "5+ years"), "2-3 years"),
    ("Experience (in years)", (), "2.5"),
    ("Total experience", ("0-1 years", "3-5 years"), None),  # 2.5 fits no option: never guess
    ("Do you have at least 2 years of professional experience?", YES_NO, "Yes"),
    ("Do you have 3+ years of experience?", YES_NO, "No"),
    ("Do you have at least 3 years of experience in Python?", YES_NO, "No"),
    ("Do you have at least 1 year of experience with Python?", YES_NO, "Yes"),
    # links (free text only, never for "how did you hear" or yes/no prompts)
    ("LinkedIn Profile", (), "https://www.linkedin.com/in/example-test"),
    ("Please share your GitHub profile URL", (), "https://github.com/example-test"),
    ("Website", (), "https://example.com"),
    ("Portfolio link", (), "https://example.com"),
    ("How did you hear about us? (LinkedIn profile link)", (), None),
    ("Do you have a portfolio website link?", YES_NO, None),
])
def test_common_ats_questions_resolve_from_stored_facts(question, options, expected):
    assert resolve_answer(question, options, FACTS) == expected


@pytest.mark.parametrize("question,options", [
    ("Current company", ()),                            # no stored fact: never invented
    ("What is your English proficiency?", ("Basic", "Fluent")),
    ("Are you authorized to work in Germany?", YES_NO),  # no row for that country
    ("Are you legally authorized to work in the country where this job is located?", YES_NO),
    ("Expected salary (USD)", ()),                       # stored CTC is INR LPA
    ("Expected hourly rate", ()),
    ("Do you have 3+ years of experience in Kotlin?", YES_NO),  # no skill_years -> no claim
])
def test_unknown_facts_return_none_for_hitl(question, options):
    assert resolve_answer(question, options, FACTS) is None


def test_current_company_and_english_only_when_stored():
    facts = CandidateFacts.from_profile({"preferences": {"current_company": "Example Labs",
                                                         "english_proficiency": "Fluent"}})
    assert resolve_answer("Current company", (), facts) == "Example Labs"
    assert resolve_answer("Current employer name", ("Other", "Example Labs"), facts) == "Example Labs"
    assert resolve_answer("How would you rate your English proficiency?", ("Basic", "Fluent", "Native"),
                          facts) == "Fluent"


def test_sensitive_and_blocked_guards_still_win():
    for question in ("Enter the OTP sent to your phone", "Passport number", "What is your ethnicity?",
                     "Email", "Do you consent to the terms and conditions?"):
        assert resolve_answer(question, (), FACTS) is None


# --- country rule ------------------------------------------------------------------------
def test_country_derivation_rules():
    assert place_facts("Bengaluru", None, None).country == "India"
    assert place_facts("Karnataka", None, None).state == "Karnataka"
    assert place_facts(None, None, "+91-90000-00000").country_source == "phone"
    assert place_facts(None, None, "+1 555 0100").country is None
    assert place_facts("London", None, "+91 90000 00000").country is None  # foreign place beats phone
    assert place_facts("Berlin, Germany", None, PHONE).country == "Germany"
    explicit = place_facts("Bengaluru", "United States", PHONE)
    assert (explicit.country, explicit.country_code, explicit.country_source) == ("United States", "US", "explicit")
    assert place_facts("Remote", None, None).city is None
    facts = CandidateFacts.from_profile({"phone": PHONE, "preferences": {}})
    assert resolve_answer("Country", ("India (+91)", "Indonesia (+62)"), facts) == "India (+91)"
    assert resolve_answer("Country", (), CandidateFacts.from_profile({"preferences": {}})) is None


def test_inr_yearly_compensation_fact_fills_ctc_but_not_other_currencies():
    inr = CandidateFacts.from_profile({"preferences": {"current_compensation": {
        "amount": "750000", "currency": "INR", "period": "year", "kind": "ctc"}}})
    assert resolve_answer("Current CTC", (), inr) == "7.5 LPA"
    usd = CandidateFacts.from_profile({"preferences": {"current_compensation": {
        "amount": "90000", "currency": "USD", "period": "year", "kind": "ctc"}}})
    assert resolve_answer("Current CTC", (), usd) is None


def test_willing_to_relocate_wins_over_open_to_relocation():
    facts = CandidateFacts.from_profile({"preferences": {"willing_to_relocate": False,
                                                         "open_to_relocation": True}})
    assert resolve_answer("Are you willing to relocate?", YES_NO, facts) == "No"


# --- resolver chain degradation (zero keys / all 429 / exceptions never raise) -----------------
def _ai(env, handler=None):
    transport = httpx.MockTransport(handler or (lambda request: httpx.Response(429, json={"error": "rate"})))
    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                         env=env, transport=transport)
    ai.bind_profile(PROFILE)
    return ai


QUESTION = "Are you comfortable with on-call rotations?"


async def test_chain_is_profile_then_cache_then_llm_then_human_with_zero_keys():
    ai = _ai({})
    assert (await ai.answerer.resolve("Country", ("India (+91)",), FACTS)).tier == 0
    miss = await ai.answerer.resolve(QUESTION, YES_NO, FACTS)
    assert (miss.tier, miss.answer, miss.reason) == (3, None, "llm_unconfigured")
    await ai.cache.store_verified_user_answer(QUESTION, "yes")
    hit = await ai.answerer.resolve(QUESTION, YES_NO, FACTS)
    assert (hit.tier, hit.source, hit.answer) == (1, "semantic_cache", "Yes")


async def test_all_providers_429_degrades_to_hitl():
    ai = _ai({"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY", "GEMINI_API_KEY": "TEST_FAKE_TOKEN_ONLY"})
    result = await ai.answerer.resolve(QUESTION, YES_NO, FACTS)
    assert (result.tier, result.answer, result.reason) == (3, None, "llm_exhausted")


async def test_transport_exception_never_raises_out_of_the_resolver():
    def boom(request):
        raise httpx.ConnectError("offline", request=request)

    ai = _ai({"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY"}, boom)
    result = await ai.answerer.resolve(QUESTION, YES_NO, FACTS)
    assert result.tier == 3 and result.answer is None


class _BrokenRouter:
    any_configured = True

    async def generate_json(self, *args, **kwargs):
        raise RuntimeError("usage store down")


class _BrokenCache(SemanticCache):
    def __init__(self):
        super().__init__(MemoryCacheStore(), DeterministicTestEmbedder())

    async def lookup(self, *args, **kwargs):
        raise ConnectionError("pgvector unavailable")


async def test_router_and_cache_exceptions_degrade_to_hitl():
    answerer = ScreeningAnswerer(_BrokenCache(), _BrokenRouter())  # type: ignore[arg-type]
    result = await answerer.resolve(QUESTION, YES_NO, FACTS)
    assert (result.tier, result.answer, result.reason) == (3, None, "llm_error:RuntimeError")
    profile_hit = await answerer.resolve("Notice period", (), FACTS)
    assert (profile_hit.tier, profile_hit.answer) == (0, "30")


# --- facts CLI ---------------------------------------------------------------------------
async def test_facts_report_masks_values_and_lists_missing():
    store = MemoryStore(profile=json.loads(json.dumps(PROFILE)))
    report = await facts_cli.facts_report(store)
    assert {"country", "city", "state", "willing_to_relocate", "linkedin_url"} <= set(report["present"])
    assert "current_company" in report["missing"] and "english_proficiency" in report["missing"]
    assert report["derived"] == {"country": "location"}
    dumped = json.dumps(report)
    for secret in ("example.com", "90000", "Bangalore", "Candidate", "linkedin.com/in"):
        assert secret not in dumped
    assert (await facts_cli.facts_report(MemoryStore()))["profile"] == "missing"


async def test_set_fact_validates_whitelists_and_flags_missing_schema_fields():
    store = MemoryStore(profile={"preferences": {}})
    ok = await facts_cli.set_fact(store, "notice_period_days", "15")
    assert ok["ok"] and store.profile["preferences"]["notice_period_days"] == 15
    assert (await facts_cli.set_fact(store, "willing_to_relocate", "yes"))["ok"]
    assert store.profile["preferences"]["willing_to_relocate"] is True
    assert (await facts_cli.set_fact(store, "current_ctc", "-5"))["ok"] is False  # schema ge=0
    assert (await facts_cli.set_fact(store, "notice_period_days", "soon"))["error"].startswith("invalid_value")
    assert (await facts_cli.set_fact(store, "email", "x@example.com"))["error"] == "key_not_allowed"
    fields = facts_cli.schema_fields()
    for key in ("country", "current_company", "english_proficiency"):
        result = await facts_cli.set_fact(store, key, "value")
        assert result["ok"] is (key in fields)
        if key not in fields:
            assert result["error"] == "schema_field_required" and key not in store.profile["preferences"]
    assert (await facts_cli.set_fact(MemoryStore(), "notice_period_days", "15"))["ok"] is False


async def test_reseed_cache_is_idempotent():
    class Store(MemoryStore):
        async def load_profile(self):
            return self.profile, [("Are you willing to work night shifts?", "No"), ("Enter your password", "x")]

    ai = _ai({})
    first = await facts_cli.reseed_cache(Store(profile={"preferences": {}}), ai)
    second = await facts_cli.reseed_cache(Store(profile={"preferences": {}}), ai)
    assert (first["inserted"], first["skipped"]) == (1, 1)
    assert second["inserted"] == 0 and first["cache_backend"] == "memory"


def test_register_and_run_parse():
    parser = argparse.ArgumentParser()
    facts_cli.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["facts", "set", "notice_period_days", "30"])
    assert (args.command, args.facts_action, args.key, args.value) == ("facts", "set", "notice_period_days", "30")
    assert parser.parse_args(["facts", "report"]).facts_action == "report"
    with pytest.raises(SystemExit):
        parser.parse_args(["facts", "set", "email", "x"])
