"""Phase 4 cache lifecycle: profile-version invalidation, quarantine (human override / portal
validation error), verified-only promotion, geography localization and decision telemetry."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.judge import JudgeVerdict
from backend.app.ai_v2.screening import ScreeningAnswerer
from backend.app.ai_v2.semantic_cache import (
    CacheTelemetry,
    MemoryCacheStore,
    QuestionContext,
    SemanticCache,
    profile_version_hash,
)
from backend.app.ai_v2.semantic_cache.promotion import promote_human_answer
from backend.app.browser_v2.adapters.shared.text import resolve_question_detail
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.answers.facts import WorkAuthorization

KIND = "screening_qa"
FACTS = CandidateFacts(experience_years=0.33, skills=("Python",), notice_period_days=30, expected_ctc="12",
                       current_ctc="9", current_location="Faridabad",
                       work_authorizations=(WorkAuthorization("IN", True, False),
                                            WorkAuthorization("US", False, True)))


class ConstantEmbedder:
    model_name, dimensions, ready = "constant", 384, True

    def __init__(self):
        self.calls = 0

    async def embed(self, text):
        self.calls += 1
        return [1.0] + [0.0] * 383


def make(embedder=None):
    return SemanticCache(MemoryCacheStore(), embedder or ConstantEmbedder(), telemetry=CacheTelemetry())


# --- profile version invalidation ------------------------------------------------------------
async def test_profile_change_invalidates_factual_but_not_behavioral_entries():
    cache = make()
    before = profile_version_hash(FACTS)
    for changed in (replace(FACTS, notice_period_days=0), replace(FACTS, expected_ctc="14")):
        assert profile_version_hash(changed) != before
    assert profile_version_hash(replace(FACTS)) == before  # deterministic
    factual_q = "How many days notice do you need to serve before joining us?"
    behavioral_q = "Tell us about yourself"
    await cache.put(KIND, factual_q, "30", "user", context=QuestionContext(profile_hash=before))
    await cache.put(KIND, behavioral_q, "I build AI products end to end.", "user",
                    context=QuestionContext(field_kind="textarea", profile_hash=before))
    after = profile_version_hash(replace(FACTS, notice_period_days=0))
    assert (await cache.lookup(KIND, factual_q, context=QuestionContext(profile_hash=before))) is not None
    assert await cache.lookup(KIND, factual_q, context=QuestionContext(profile_hash=after)) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_stale_profile"] == 1
    behavioral = await cache.lookup(KIND, behavioral_q,
                                    context=QuestionContext(field_kind="textarea", profile_hash=after))
    assert behavioral is not None and behavioral.entry.meta.invalidation_scope == "behavioral_stable"
    assert behavioral.entry.meta.expires_at is not None  # 180-day TTL


async def test_legacy_factual_row_without_a_profile_hash_is_treated_as_stale():
    cache = make()
    await cache.store.upsert(KIND, "What is your expected CTC in LPA?", "what is your expected ctc in lpa", None,
                             "6", "user")  # pre-006 row: no metadata at all
    query = QuestionContext(profile_hash=profile_version_hash(FACTS))
    assert await cache.lookup(KIND, "What is your expected CTC in LPA?", context=query) is None
    assert (await cache.lookup(KIND, "What is your expected CTC in LPA?")).answer is None  # context-free: legacy


async def test_notice_question_variant_is_answered_from_profile_not_a_stale_cache_row():
    cache = make()
    await cache.store.upsert(KIND, "How many days notice do you need to serve?",
                             "how many days notice do you need to serve", None, "60", "user")
    answerer = ScreeningAnswerer(cache, None)
    resolved = await answerer.resolve("How many days notice do you need to serve?", (),
                                      replace(FACTS, notice_period_days=0))
    assert resolved.tier == 0 and resolved.answer == "0"


# --- quarantine --------------------------------------------------------------------------------
async def test_human_override_quarantines_the_contradicted_entry():
    cache = make()
    old = await cache.put(KIND, "How many years of experience do you have with Docker containers?", "5", "profile")
    await cache.store_verified_user_answer("Years of experience you have with Docker containers in production?", "1")
    entry = await cache.store.get(old.entry.id)
    assert entry.status == "quarantined" and entry.human_override_count == 1
    assert entry.quarantine_reason == "human_override"
    hit = await cache.lookup(KIND, "How many years of experience do you have with Docker containers?")
    assert hit is not None and hit.entry.answer_text == "1"  # the bad row is never served again
    stats = await cache.stats()
    assert stats["status_counts"]["quarantined"] == 1 and stats["decisions"]["counters"]["quarantined"] == 1


async def test_form_validation_error_quarantines_and_unquarantine_restores():
    cache = make()
    put = await cache.put(KIND, "Are you willing to work night shifts?", "Maybe", "user")
    entry = await cache.record_form_validation_error(put.entry.id)
    assert entry.status == "quarantined" and entry.form_validation_error_count == 1
    assert await cache.lookup(KIND, "Are you willing to work night shifts?") is None
    restored = await cache.unquarantine(put.entry.id)
    assert restored.status == "active" and restored.form_validation_error_count == 1
    assert await cache.lookup(KIND, "Are you willing to work night shifts?") is not None
    await cache.quarantine(put.entry.id, "owner")
    assert await cache.purge(status="quarantined") == 1 and (await cache.stats())["total_entries"] == 0


async def test_exact_hit_uses_zero_embedding_calls_with_full_context():
    embedder = ConstantEmbedder()
    cache = make(embedder)
    await cache.put(KIND, "Q1. Are you willing to work night shifts? *", "No", "user",
                    context=QuestionContext(field_kind="radio", options=("Yes", "No")))
    calls = embedder.calls
    hit = await cache.lookup(KIND, "are you willing to work night shifts",
                             context=QuestionContext(field_kind="select", options=("Yes", "No")))
    assert hit is not None and hit.match == "exact" and hit.answer == "No"
    assert embedder.calls == calls


# --- verified-only promotion ------------------------------------------------------------------
class StubRouter:
    any_configured = True
    env = {}
    tracer = None

    def __init__(self, answer="Yes"):
        self.answer = answer
        self.calls = 0

    async def generate_json(self, task, system, prompt, model, **kwargs):
        self.calls += 1
        value = model(answer=self.answer, confidence=0.97, needs_human=False, cacheable=True, reason="profile")
        return SimpleNamespace(value=value, provider="groq", model="m", input_tokens=1, output_tokens=1,
                               trace_id=None)


class StubJudge:
    enforce = False

    def __init__(self, verdict):
        self.verdict = verdict

    async def review(self, **kwargs):
        return self.verdict


@pytest.mark.parametrize("verdict,cached", [
    (None, False),
    (JudgeVerdict(True, 0.90, "ok", "gemini", "g"), False),
    (JudgeVerdict(False, 0.99, "no", "gemini", "g"), False),
    (JudgeVerdict(True, 0.95, "ok", "gemini", "g"), True),
])
async def test_llm_answers_are_cached_only_when_the_judge_approves_with_score_092(verdict, cached):
    cache = make()
    router = StubRouter()
    answerer = ScreeningAnswerer(cache, router, judge=StubJudge(verdict))
    question = "Are you comfortable working in a fast-paced startup environment?"
    first = await answerer.resolve(question, ("Yes", "No"), FACTS, {"company": "Acme"})
    assert first.answer == "Yes" and first.cached_new is cached
    rows, _ = await cache.store.list_entries(None, None, 10, 0)
    assert len(rows) == int(cached)
    if cached:
        assert rows[0].trust == "llm_verified" and rows[0].meta.verified_by.startswith("judge:gemini:0.95")
        again = await answerer.resolve(question, ("Yes", "No"), FACTS, {"company": "Acme"})
        assert again.tier == 1 and again.cache_entry_id == rows[0].id and router.calls == 1


# --- geography: the audit's two leaks ----------------------------------------------------------
async def test_sponsorship_for_an_unlisted_country_never_reuses_another_countrys_answer():
    cache = make()
    await cache.put(KIND, "Will you now or in the future require visa sponsorship to work in India?", "No", "user")
    facts = replace(FACTS, work_authorizations=(WorkAuthorization("IN", True, False),))  # no US row
    answerer = ScreeningAnswerer(cache, None)
    us = await answerer.resolve("Will you now or in the future require visa sponsorship to work in the US?",
                                ("Yes", "No"), facts)
    assert us.answer is None and us.tier == 3
    generic = await answerer.resolve("Will you now or in the future require visa sponsorship?", ("Yes", "No"),
                                     facts)
    assert (generic.answer, generic.reason) == (None, "work_auth_country_unknown")
    localized = await answerer.resolve("Will you now or in the future require visa sponsorship?", ("Yes", "No"),
                                       facts, {"role_country": "India"})
    assert localized.tier == 0 and localized.answer == "No"


async def test_hitl_answer_is_cached_with_the_job_country_and_never_served_for_another_country():
    cache = make()
    hitl = SimpleNamespace(ref="abc123", options=("Yes", "No"),
                           prompt_text="Are you authorized to work in the country in which this role is located?",
                           context={"company": "Acme", "context": {"role_country": "India", "field_kind": "radio"}})
    assert await promote_human_answer(cache, hitl, "Yes") is True
    rows, _ = await cache.store.list_entries(None, None, 10, 0)
    assert "india" in rows[0].normalized_question and rows[0].meta.entities.get("country") == ["IN"]
    assert await cache.lookup(KIND, "Are you authorized to work in the United States?",
                              context=QuestionContext(options=("Yes", "No"))) is None
    unknown = SimpleNamespace(ref="def456", options=("Yes", "No"), prompt_text=hitl.prompt_text,
                              context={"company": "Acme", "context": {}})
    assert await promote_human_answer(cache, unknown, "Yes") is False  # geo_unknown: one-time answer


async def test_form_field_prompt_is_localized_for_the_hitl_card():
    detail = SimpleNamespace(location="Bengaluru, India", listing=SimpleNamespace(title="SWE", company="Acme"))
    result = await resolve_question_detail("Will you require sponsorship?", ("Yes", "No"), CandidateFacts(),
                                           detail, None, None, field_kind="radio", platform="greenhouse")
    assert result.answer is None and result.prompt == "Will you require sponsorship? (job country: India)"
    assert result.role_country == "India"
    naukri = SimpleNamespace(location=None, listing=SimpleNamespace(title="SWE", company="Acme"))
    local = await resolve_question_detail("Are you authorized to work?", ("Yes", "No"), FACTS, naukri, None, None,
                                          platform="naukri")
    assert local.answer == "Yes"  # India-only portal -> Indian work authorization from the profile


async def test_decision_stats_shape():
    cache = make(DeterministicTestEmbedder())
    await cache.put(KIND, "Are you willing to work night shifts?", "No", "user")
    await cache.lookup(KIND, "Are you willing to work night shifts?")
    snapshot = cache.telemetry.snapshot()
    assert snapshot["counters"]["exact_hit"] == 1 and snapshot["counters"]["promoted_human"] == 1
    assert set(snapshot) == {"since", "lookups", "hits", "hit_rate", "counters", "rejections"}
