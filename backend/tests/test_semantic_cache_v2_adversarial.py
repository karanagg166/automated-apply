"""Phase 4 adversarial semantic-cache cases: a high cosine score must never be enough.

`ConstantEmbedder` embeds every text identically (cosine 1.0), so every rejection below is made by
a guard (entity / polarity / scope / cross-company / option / field type), never by the threshold.
"""

import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder, cosine
from backend.app.ai_v2.semantic_cache import (
    CacheTelemetry,
    InvalidCacheEntry,
    MemoryCacheStore,
    QuestionContext,
    SemanticCache,
    classify_intent,
    normalize_question,
)

KIND = "screening_qa"


class ConstantEmbedder:
    model_name, dimensions, ready = "constant", 384, True

    def __init__(self):
        self.calls = 0

    async def embed(self, text):
        self.calls += 1
        return [1.0] + [0.0] * 383


def make(embedder=None):
    return SemanticCache(MemoryCacheStore(), embedder or ConstantEmbedder(), telemetry=CacheTelemetry())


def ctx(**kwargs):
    return QuestionContext(**kwargs)


@pytest.mark.parametrize("cached,query", [
    ("How many years of experience do you have in Java?", "How many years of experience do you have in JavaScript?"),
    ("How many years of experience do you have in JavaScript?", "How many years of experience do you have in Java?"),
    ("How many years of experience do you have in C?", "How many years of experience do you have in C++?"),
    ("Years of experience with C++?", "Years of experience with C#?"),
    ("How many years of experience do you have with React?",
     "How many years of experience do you have with React Native?"),
    ("How many years of experience do you have with React Native?",
     "How many years of experience do you have with React?"),
    ("Years of experience with Spring?", "Years of experience with Spring Boot?"),
    ("Years of experience with SQL?", "Years of experience with NoSQL?"),
    ("Years of experience with Python?", "Years of experience with PyTorch?"),
    ("Years of experience with AWS?", "Years of experience with GCP?"),
])
async def test_tech_entities_never_cross_match(cached, query):
    cache = make()
    await cache.put(KIND, cached, "3", "user")
    assert await cache.lookup(KIND, query) is None
    assert await cache.lookup(KIND, query, context=ctx(field_kind="number")) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_entity_mismatch"] >= 2


async def test_react_native_is_not_react_even_with_the_real_bag_of_words_embedder():
    cache = make(DeterministicTestEmbedder())
    await cache.put(KIND, "How many years of experience do you have with React Native?", "3", "user")
    hit = await cache.lookup(KIND, "How many years of experience do you have with React?")
    assert hit is None


@pytest.mark.parametrize("cached,query", [
    ("Are you authorized to work in India?", "Are you authorized to work in the United States?"),
    ("Are you authorized to work in India?", "Are you authorized to work in the US?"),
    ("Are you legally authorized to work in the UK?", "Are you legally authorized to work in Canada?"),
    ("Are you authorized to work in the EU?", "Are you authorized to work in India?"),
    ("Are you willing to relocate to Pune?", "Are you willing to relocate to Bengaluru?"),
    ("Are you open to remote work?", "Are you open to hybrid work?"),
])
async def test_geography_and_work_mode_never_cross_match(cached, query):
    cache = make()
    await cache.put(KIND, cached, "Yes", "user")
    assert await cache.lookup(KIND, query, context=ctx(options=("Yes", "No"))) is None


@pytest.mark.parametrize("cached,query", [
    ("Are you legally authorized to work in India without sponsorship?",
     "Will you require visa sponsorship to work in India now or in the future?"),
    ("Will you require visa sponsorship to work in India now or in the future?",
     "Are you legally authorized to work in India without sponsorship?"),
    ("Are you willing to relocate to Pune?", "Are you currently located in Pune?"),
    ("What is your minimum expected salary in LPA?", "What is your current salary in LPA?"),
    ("Have you ever been employed by Acme?", "Are you currently employed by Acme?"),
    ("Are you 18 years of age or older?", "Are you under 18?"),
])
async def test_polarity_flips_are_rejected(cached, query):
    cache = make()
    await cache.put(KIND, cached, "Yes", "user")
    assert await cache.lookup(KIND, query, context=ctx(options=("Yes", "No"))) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_polarity_flip"] >= 1 \
        or cache.telemetry.snapshot()["counters"]["rejected_intent"] >= 1


async def test_sponsorship_without_a_country_is_never_written_or_served():
    cache = make()
    with pytest.raises(InvalidCacheEntry, match="geo_unknown"):
        await cache.put(KIND, "Will you now or in the future require visa sponsorship?", "No", "user",
                        context=ctx(options=("Yes", "No")))
    await cache.put(KIND, "Will you now or in the future require visa sponsorship to work in India?", "No", "user")
    # The audit's leak: a country-specific question must not be answered by another country's row.
    assert await cache.lookup(KIND, "Will you now or in the future require visa sponsorship to work in the US?",
                              context=ctx(options=("Yes", "No"))) is None


async def test_company_motivation_is_company_scoped():
    cache = make()
    await cache.put(KIND, "Why do you want to join Stripe?", "I love Stripe's developer-first payments.", "user",
                    context=ctx(company="Stripe", field_kind="textarea"))
    assert classify_intent("Why do you want to join Razorpay?") == "company_motivation"
    assert await cache.lookup(KIND, "Why do you want to join Razorpay?",
                              context=ctx(company="Razorpay", field_kind="textarea")) is None
    assert await cache.lookup(KIND, "Why do you want to work here?",
                              context=ctx(company="Razorpay", field_kind="textarea")) is None
    same = await cache.lookup(KIND, "Why do you want to join Stripe?",
                              context=ctx(company="Stripe", field_kind="textarea"))
    assert same is not None and same.match == "exact"
    with pytest.raises(InvalidCacheEntry, match="company_unknown"):
        await cache.put(KIND, "Why do you want to work here?", "Because.", "user")


async def test_cross_company_contamination_guard_on_global_answers():
    cache = make()
    await cache.put(KIND, "Tell us about yourself", "I am an AI engineer who wants to build payments at Stripe.",
                    "user", context=ctx(company="Stripe", field_kind="textarea"))
    assert await cache.lookup(KIND, "Tell us about yourself",
                              context=ctx(company="Razorpay", field_kind="textarea")) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_cross_company"] >= 1
    assert await cache.lookup(KIND, "Tell us about yourself",
                              context=ctx(company="Stripe", field_kind="textarea")) is not None


async def test_option_set_mismatch_rejects_and_tries_the_next_candidate():
    cache = make()
    await cache.put(KIND, "What is your notice period in days?", "60 Days", "user")
    options = ("Immediate", "15 Days", "30 Days")
    assert await cache.lookup(KIND, "What is your notice period in days?", context=ctx(options=options)) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_option_mismatch"] >= 1
    rows, _ = await cache.store.list_entries(None, None, 10, 0)
    assert rows[0].hits == 0  # a rejected candidate is never counted as a hit
    # Synonyms still map: "Yes, I am" -> the single Yes option.
    await cache.put(KIND, "Are you comfortable with on-call rotations?", "Yes, I am", "user")
    hit = await cache.lookup(KIND, "Are you comfortable with on-call rotations?",
                             context=ctx(options=("Yes", "No")))
    assert hit is not None and hit.answer == "Yes"


async def test_long_text_never_fills_a_boolean_field():
    cache = make()
    paragraph = "I have built three production FastAPI services and a RAG pipeline over two years."
    await cache.put(KIND, "Describe your Python experience", paragraph, "user", context=ctx(field_kind="textarea"))
    assert await cache.lookup(KIND, "Describe your Python experience",
                              context=ctx(field_kind="radio", options=("Yes", "No"))) is None
    assert cache.telemetry.snapshot()["counters"]["rejected_field_type"] >= 1


async def test_never_cache_prompts_are_refused():
    cache = make()
    for question in ("Please paste a cover letter for this role", "Write a function to reverse a linked list"):
        with pytest.raises(InvalidCacheEntry, match="never_cache"):
            await cache.put(KIND, question, "text", "user")
        assert await cache.lookup(KIND, question) is None


async def test_factual_threshold_is_stricter_than_long_text():
    embedder = DeterministicTestEmbedder()
    cache = make(embedder)
    cached = "Are you willing to work rotational night shifts at our office"
    query = "Are you willing to work rotational night shifts at our office sometimes"
    similarity = cosine(await embedder.embed(normalize_question(cached)), await embedder.embed(normalize_question(query)))
    assert 0.88 <= similarity < 0.93 + 0.04
    await cache.put(KIND, cached, "Yes", "user")
    typed = await cache.lookup(KIND, query, context=ctx(options=("Yes", "No")))
    assert (typed is None) == (similarity < 0.93)
    assert await cache.lookup(KIND, query) is not None  # context-free callers keep the 0.88 floor
