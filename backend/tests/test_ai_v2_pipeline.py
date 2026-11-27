"""4-tier screening pipeline, gray-zone JD scoring and graceful worker degradation."""

import json

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.adapters.base import ApplyResult, HitlQuestion
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.rules import CandidatePreferences, title_gray_zone
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.tests.test_browser_v2_worker import (
    FakeAdapter,
    FakeManager,
    build,
    job,
    live_store,
    rules,
)

KEYS = {"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY", "GEMINI_API_KEY": "TEST_FAKE_TOKEN_ONLY"}
PROFILE = {
    "full_name": "Test Candidate Person", "phone": "+91 98765 43210", "email": "test.candidate@gmail.com",
    "verified_experience_years": 2, "verified_skills": ["Python", "FastAPI"],
    "preferences": {"target_roles": ["Backend Engineer"], "tech_stack": ["Python"], "notice_period_days": 30,
                    "skill_years": {"python": 2}, "current_location": "Bengaluru"},
}
FACTS = CandidateFacts.from_profile(PROFILE)


class LLM:
    """Scripted OpenAI/Gemini-shaped replies; records every request body."""

    def __init__(self, reply=None, status=200):
        self.reply = reply if reply is not None else {"answer": "Yes", "confidence": 0.9, "needs_human": False,
                                                      "cacheable": True, "reason": "profile"}
        self.status = status
        self.bodies: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        text = json.dumps(self.reply)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 120, "completion_tokens": 20}})


def runtime(llm=None, env=None):
    llm = llm or LLM()
    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                         env=KEYS if env is None else env, transport=httpx.MockTransport(llm.handler))
    ai.bind_profile(PROFILE)
    return ai, llm


# --- Tier 0 -> 1 -> 2 -> 3 -------------------------------------------------------------
async def test_tier0_profile_fact_needs_no_cache_or_llm():
    ai, llm = runtime()
    result = await ai.answerer.resolve("What is your notice period?", (), FACTS)
    assert (result.tier, result.source, result.answer) == (0, "profile", "30")
    assert llm.bodies == [] and (await ai.cache.stats())["total_hits"] == 0


async def test_tier1_cache_hit_costs_zero_llm_calls_and_fits_options():
    ai, llm = runtime()
    await ai.cache.store_verified_user_answer("Are you willing to work night shifts?", "no")
    result = await ai.answerer.resolve("Are you willing to work night shifts?", ("Yes", "No"), FACTS)
    assert (result.tier, result.answer, result.cache_match) == (1, "No", "exact")
    similar = await ai.answerer.resolve("Are you willing to work night shifts sometimes?", ("Yes", "No"), FACTS)
    assert similar.tier == 1 and similar.cache_match == "semantic" and similar.answer == "No"
    assert llm.bodies == []


async def test_tier2_unjudged_llm_answer_is_used_but_never_cached():
    """Phase 4 (poison-proof cache): an LLM answer is reused only after an approving judge verdict
    (score >= 0.92, see test_ai_v2_observability); without a verdict it is used once and not cached."""
    ai, llm = runtime()
    question = "Are you comfortable working in a fast-paced startup environment?"
    first = await ai.answerer.resolve(question, ("Yes", "No"), FACTS)
    assert (first.tier, first.source, first.answer, first.cached_new) == (2, "llm", "Yes", False)
    assert first.provider == "groq" and first.input_tokens == 120 and first.output_tokens == 20
    body = json.loads(llm.bodies[0])["messages"][1]["content"]
    assert '"options": ["Yes", "No"]' in body and "skill_years" in body
    assert "98765" not in body and "Candidate Person" not in body and "gmail" not in body
    second = await ai.answerer.resolve(question, ("Yes", "No"), FACTS)
    assert second.tier == 2 and len(llm.bodies) == 2  # not cached: asked again
    assert (await ai.cache.stats())["total_entries"] == 0


@pytest.mark.parametrize("reply,reason", [
    ({"answer": "Yes", "confidence": 0.7, "needs_human": False, "cacheable": True}, "llm_low_confidence"),
    ({"answer": "Yes", "confidence": 0.95, "needs_human": True, "cacheable": True}, "llm_needs_human"),
    ({"answer": None, "confidence": 0.95, "needs_human": False, "cacheable": True}, "llm_needs_human"),
    ({"answer": "Maybe", "confidence": 0.95, "needs_human": False, "cacheable": True}, "llm_answer_not_an_option"),
])
async def test_tier3_when_llm_is_unsure_or_off_option(reply, reason):
    ai, _ = runtime(LLM(reply))
    result = await ai.answerer.resolve("Are you comfortable with on-call rotations?", ("Yes", "No"), FACTS)
    assert (result.tier, result.answer, result.reason) == (3, None, reason)
    assert (await ai.cache.stats())["total_entries"] == 0


async def test_accepted_but_below_cache_confidence_is_not_cached():
    ai, _ = runtime(LLM({"answer": "Yes", "confidence": 0.82, "needs_human": False, "cacheable": True}))
    result = await ai.answerer.resolve("Are you comfortable with on-call rotations?", ("Yes", "No"), FACTS)
    assert result.tier == 2 and not result.cached_new and (await ai.cache.stats())["total_entries"] == 0
    ai2, _ = runtime(LLM({"answer": "Yes", "confidence": 0.95, "needs_human": False, "cacheable": False}))
    assert not (await ai2.answerer.resolve("Why do you want to join Example Corp?", (), FACTS)).cached_new


@pytest.mark.parametrize("question,reason", [
    ("Enter the OTP sent to your phone", "sensitive_or_blocked_question"),
    ("Do you consent to a background verification?", "sensitive_or_blocked_question"),
    ("What is your date of birth?", "private_or_unverifiable_data"),
    ("Please share your LinkedIn profile URL", "private_or_unverifiable_data"),
    ("What is your reporting manager's name?", "private_or_unverifiable_data"),
])
async def test_private_or_sensitive_questions_never_reach_the_llm(question, reason):
    ai, llm = runtime()
    result = await ai.answerer.resolve(question, (), FACTS)
    assert (result.tier, result.reason) == (3, reason) and llm.bodies == []


async def test_user_taught_private_answer_is_served_from_cache():
    ai, llm = runtime()
    await ai.cache.store_verified_user_answer("Please share your GitHub profile URL", "https://github.com/example")
    result = await ai.answerer.resolve("Please share your GitHub profile URL", (), FACTS)
    assert result.tier == 1 and llm.bodies == []


async def test_exhausted_or_unconfigured_router_falls_back_to_hitl():
    ai, llm = runtime(LLM(status=503))
    result = await ai.answerer.resolve("Are you comfortable with on-call rotations?", ("Yes", "No"), FACTS)
    assert (result.tier, result.reason) == (3, "llm_exhausted") and len(llm.bodies) == 2
    assert result.llm_chain[:3] == ("groq:http_503", "cerebras:unconfigured", "gemini:http_503")
    bare, bare_llm = runtime(env={})
    result = await bare.answerer.resolve("Are you comfortable with on-call rotations?", ("Yes", "No"), FACTS)
    assert (result.tier, result.reason) == (3, "llm_unconfigured") and bare_llm.bodies == []


async def test_naukri_adapter_uses_the_tiered_resolver_when_injected():
    ai, _ = runtime()
    adapter = NaukriAdapter()
    detail = type("D", (), {"listing": job(1)})()
    assert (await adapter._resolve("Notice period?", (), FACTS, detail))[1] == "profile"  # deterministic only
    BrowserService(FakeManager(), MemoryStore(), adapters={"naukri": adapter}, ai=ai)  # type: ignore[arg-type]
    assert adapter.answerer is ai.answerer
    answer, source, reason = await adapter._resolve("Are you okay with weekend deployments?", ("Yes", "No"),
                                                    FACTS, detail)
    assert (answer, source, reason) == ("Yes", "llm", "llm_accepted")


# --- gray-zone JD scoring --------------------------------------------------------------
def test_title_gray_zone_detection():
    prefs = CandidatePreferences(target_roles=("Backend Engineer",))
    assert title_gray_zone("Software Engineer", prefs)
    assert title_gray_zone("Python Developer - Backend", prefs) is False  # strict match already passes
    assert not title_gray_zone("Sales Executive", prefs)
    assert not title_gray_zone("Software Engineer", CandidatePreferences())


def gray_store():
    return MemoryStore(rules={"naukri": rules(auto_apply_enabled=False)}, profile=PROFILE)


async def run_gray(llm_reply, env=KEYS, title="Software Engineer", description="Build Python FastAPI services"):
    ai, llm = runtime(LLM(llm_reply), env=env)
    adapter = FakeAdapter("naukri", [job(1, title=title)], details={"naukri-1": {"description": description}})
    service = BrowserService(FakeManager(), gray_store(), adapters={"naukri": adapter}, ai=ai)  # type: ignore[arg-type]
    return await service.process_job(job(1, title=title), dry_run=True, record_filters=True), llm, adapter, service


async def test_gray_zone_title_accepted_by_llm_reaches_apply():
    outcome, llm, _adapter, _ = await run_gray({"match": True, "score": 0.86, "reason": "backend python role"})
    assert outcome["reason"] == "dry_run_stopped_before_apply_click"
    assert any(r.startswith("llm_jd_match: 0.86") for r in outcome["filter_reasons"])
    assert json.loads(llm.bodies[0])["systemInstruction"]  # jd_scoring routes to Gemini first


async def test_gray_zone_title_rejected_by_llm_is_filtered_and_decision_cached():
    outcome, llm, _, service = await run_gray({"match": False, "score": 0.3, "reason": "frontend heavy"})
    assert outcome["state"] == S.FILTERED_OUT.value and "llm_jd_reject: 0.30 via llm" in outcome["reason"]
    rows, _ = await service.ai.cache.store.list_entries("jd_score", None, 10, 0)
    assert len(rows) == 1 and json.loads(rows[0].answer_text)["score"] == 0.3
    decision = await service.ai.jd_scorer.score(title="Software Engineer", company="Company 1",
                                                description="Build Python FastAPI services",
                                                target_roles=("Backend Engineer",))
    assert decision.source == "cache" and len(llm.bodies) == 1


async def test_no_llm_keys_keeps_the_deterministic_title_filter():
    outcome, llm, _adapter, service = await run_gray({}, env={})
    assert outcome["state"] == S.FILTERED_OUT.value and outcome["reason"].startswith("title_not_in_target_roles")
    assert llm.bodies == []
    prefs = CandidatePreferences.from_profile(PROFILE)
    _, verdict = await service.prefilter(job(2, title="Software Engineer"), rules(), prefs, record_filters=False)
    assert verdict is not None  # card-level filter still applies without an LLM


async def test_hard_filters_run_before_any_llm_call():
    outcome, llm, _adapter, _ = await run_gray({"match": True, "score": 0.99},
                                              title="Software Engineer", description="We need PHP Laravel")
    # tech_stack (Python) missing from the JD: the hard filter rejects before the tie-breaker.
    assert outcome["state"] == S.FILTERED_OUT.value and llm.bodies == []


async def test_prefilter_lets_gray_zone_titles_through_only_with_a_scorer():
    ai, _ = runtime()
    service = BrowserService(FakeManager(), gray_store(), ai=ai)  # type: ignore[arg-type]
    prefs = CandidatePreferences.from_profile(PROFILE)
    _, verdict = await service.prefilter(job(3, title="Software Engineer"), rules(), prefs, record_filters=False)
    assert verdict is None
    _, verdict = await service.prefilter(job(4, title="Sales Executive"), rules(), prefs, record_filters=False)
    assert verdict is not None


# --- worker degrades gracefully when every provider is down -------------------------------
class QuestionAdapter(FakeAdapter):
    """Live apply asks one unseen screening question through the injected tiered resolver."""

    answerer = None

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        self.applied.append((detail.listing.external_job_id, dry_run))
        resolved = await self.answerer.resolve("Are you okay with weekend on-call?", ("Yes", "No"), profile)
        if resolved.answer is None:
            return ApplyResult(S.WAITING_FOR_USER, "question_requires_owner", False, clicked_apply=True,
                               question=HitlQuestion(kind="QUESTION", prompt="Are you okay with weekend on-call?"))
        return ApplyResult(S.APPLIED, "confirmed", False, clicked_apply=True, receipt={"source": "fake"})


async def test_worker_cycle_survives_all_llm_providers_exhausted():
    ai, llm = runtime(LLM(status=503))
    store = live_store({"naukri": rules()})
    adapter = QuestionAdapter("naukri", [job(1), job(2)])
    worker, _ = build(store, {"naukri": adapter})
    worker.service.ai = ai
    adapter.answerer = ai.answerer
    report = await worker.cycle(run_once=True)
    portal = report.portals[0]
    assert portal.errors == 0 and portal.waiting_for_user == 2  # non-blocking: both jobs processed
    assert [a for a in adapter.applied] == [("naukri-1", False), ("naukri-2", False)]
    assert len(store.hitl) == 2
    # After the first exhaustion both providers are cooling down: the second job made no HTTP calls.
    assert len(llm.bodies) == 2
