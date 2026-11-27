"""Langfuse tracing of the LLM router and the LLM-as-judge gate on screening answers.

Everything is offline: a recording tracer for behaviour, and the real Langfuse SDK wired to an
in-memory OpenTelemetry exporter to prove the SDK calls we make are valid (no network).
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.judge import AnswerJudge, judge_mode
from backend.app.ai_v2.observability import (
    LangfuseTracer,
    NullTracer,
    scrub_payload,
    tracer_from_env,
    tracing_configured,
)
from backend.app.ai_v2.router import (
    AllLLMProvidersExhaustedError,
    LLMRouter,
    provider_family,
)
from backend.app.ai_v2.screening import ScreeningAnswerer
from backend.app.ai_v2.semantic_cache import MemoryCacheStore, SemanticCache
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.answers import CandidateFacts

FAKE = "TEST_FAKE_TOKEN_ONLY"
KEYS = {"GROQ_API_KEY": FAKE, "GEMINI_API_KEY": FAKE}
GROQ, GEMINI = "api.groq.com", "generativelanguage.googleapis.com"
QUESTION = "Are you comfortable working in rotational shifts?"
SAFE_PROFILE = {"skills": ["Python"], "total_experience_years": 0.33}
FACTS = CandidateFacts.from_profile({"full_name": "Test Candidate Person", "preferences": {}})
ANSWER = {"answer": "Yes", "confidence": 0.95, "needs_human": False, "cacheable": True, "reason": "profile"}


class Reply(BaseModel):
    answer: str
    confidence: float


class RecordingCall:
    def __init__(self, tracer, task):
        self.tracer, self.task, self.trace_id = tracer, task, f"trace-{len(tracer.calls) + 1}"
        self.attempts: list[dict] = []
        self.finished: tuple | None = None

    def attempt(self, provider, model, max_output_tokens):
        entry = {"provider": provider, "model": model}
        self.attempts.append(entry)
        call = self

        class Span:
            def ok(self, text, input_tokens, output_tokens):
                entry.update(outcome="ok", text=text, tokens=(input_tokens, output_tokens))

            def fail(self, outcome):
                entry.update(outcome=outcome)
                assert call.finished is None, "an attempt must close before the call finishes"

        return Span()

    def finish(self, outcome, attempts, provider=None):
        assert self.finished is None, "finish must run exactly once"
        self.finished = (outcome, provider)


class RecordingTracer:
    enabled = True

    def __init__(self):
        self.calls: list[RecordingCall] = []
        self.inputs: list[tuple[str, str]] = []
        self.scores: list[tuple] = []
        self.secrets: tuple[str, ...] = ()

    def register_secrets(self, secrets):
        self.secrets = tuple(secrets)

    def start_call(self, task, system, user):
        self.inputs.append((system, user))
        call = RecordingCall(self, task)
        self.calls.append(call)
        return call

    def score(self, trace_id, name, value, *, comment=None):
        self.scores.append((trace_id, name, value, comment))

    def flush(self):
        return None

    def named(self, name):
        return [score for score in self.scores if score[1] == name]


def wire(host, payload):
    text = json.dumps(payload)
    if host == GEMINI:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                     "usage": {"prompt_tokens": 30, "completion_tokens": 5}})


def make_router(replies, tracer=None, env=KEYS):
    """`replies[host]` is a payload dict, an HTTP status int, or a callable(request) -> payload."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        reply = replies[request.url.host]
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": "x"})
        return wire(request.url.host, reply)

    router = LLMRouter(env=dict(env), usage=MemoryUsageStore(), transport=httpx.MockTransport(handler),
                       tracer=tracer)
    return router, seen


# --- configuration -----------------------------------------------------------------------------
def test_tracing_is_off_without_keys_and_with_the_kill_switch():
    assert not tracing_configured({})
    assert not tracing_configured({"LANGFUSE_PUBLIC_KEY": FAKE})
    both = {"LANGFUSE_PUBLIC_KEY": FAKE, "LANGFUSE_SECRET_KEY": FAKE}
    assert tracing_configured(both)
    assert not tracing_configured(both | {"LANGFUSE_TRACING_ENABLED": "false"})
    assert isinstance(tracer_from_env({}), NullTracer)
    assert isinstance(LLMRouter(env=dict(KEYS), usage=MemoryUsageStore()).tracer, NullTracer)


def test_provider_family_groups_extra_key_slots():
    assert provider_family("groq_2") == provider_family("groq") == "groq"
    assert provider_family("github_models") == "github_models"


def test_payload_scrub_reaches_nested_strings():
    scrubbed = scrub_payload({"a": ["call +91 98765 43210", {"b": "Zed Example"}], "n": 3}, ["Zed Example"])
    assert "98765" not in json.dumps(scrubbed) and "Zed Example" not in json.dumps(scrubbed)
    assert scrubbed["n"] == 3


# --- router tracing ----------------------------------------------------------------------------
async def test_success_is_one_trace_with_one_generation_and_a_trace_id():
    tracer = RecordingTracer()
    router, _ = make_router({GROQ: {"answer": "Yes", "confidence": 0.9}}, tracer)
    result = await router.generate_json("screening_qa", "sys", "user", Reply)
    call = tracer.calls[0]
    assert result.trace_id == call.trace_id == "trace-1"
    assert call.task == "screening_qa" and call.finished == ("ok", "groq")
    assert [(a["provider"], a["outcome"], a["tokens"]) for a in call.attempts] == [("groq", "ok", (30, 5))]


async def test_failover_records_the_failed_attempt_then_the_winner():
    tracer = RecordingTracer()
    router, _ = make_router({GROQ: 503, GEMINI: {"answer": "Yes", "confidence": 0.9}}, tracer)
    result = await router.generate_json("screening_qa", "sys", "user", Reply)
    call = tracer.calls[0]
    assert result.provider == "gemini" and call.finished == ("ok", "gemini")
    assert [(a["provider"], a["outcome"]) for a in call.attempts] == [("groq", "http_503"), ("gemini", "ok")]


async def test_exhaustion_closes_the_trace_and_still_raises():
    tracer = RecordingTracer()
    router, _ = make_router({GROQ: 429, GEMINI: 500}, tracer)
    with pytest.raises(AllLLMProvidersExhaustedError):
        await router.generate_json("screening_qa", "sys", "user", Reply)
    assert tracer.calls[0].finished == ("exhausted", None)
    assert [a["outcome"] for a in tracer.calls[0].attempts] == ["http_429", "http_500"]


async def test_only_scrubbed_prompts_reach_the_tracer():
    tracer = RecordingTracer()
    router, _ = make_router({GROQ: {"answer": "Yes", "confidence": 0.9}}, tracer)
    router.register_secrets(["Zed Example"])
    await router.generate_json("screening_qa", "sys", "I am Zed Example, phone +91 98765 43210", Reply)
    _, user = tracer.inputs[0]
    assert "Zed Example" not in user and "98765" not in user
    assert tracer.secrets == ("Zed Example",)


async def test_a_broken_tracer_never_breaks_the_llm_call():
    class Broken:
        def update(self, **_):
            raise RuntimeError("langfuse down")

        def start_observation(self, **_):
            raise RuntimeError("langfuse down")

        def create_score(self, **_):
            raise RuntimeError("langfuse down")

    tracer = LangfuseTracer(Broken())
    router, _ = make_router({GROQ: {"answer": "Yes", "confidence": 0.9}}, tracer)
    result = await router.generate_json("screening_qa", "sys", "user", Reply)
    assert result.value.answer == "Yes" and result.trace_id is None
    tracer.score("trace-x", "answer_accepted", True)  # swallowed


async def test_exclude_skips_the_whole_provider_family():
    router, seen = make_router({GROQ: {"answer": "Yes", "confidence": 0.9},
                                GEMINI: {"answer": "No", "confidence": 0.9}},
                               env=KEYS | {"GROQ_API_KEY_2": FAKE})
    result = await router.generate_json("screening_qa", "sys", "user", Reply, exclude=("groq_2",))
    assert result.provider == "gemini" and seen == [GEMINI]
    assert {a["provider"]: a["outcome"] for a in result.attempts}["groq"] == "excluded"


# --- real SDK (offline) ------------------------------------------------------------------------
async def test_real_langfuse_sdk_accepts_our_calls_and_exports_only_scrubbed_spans():
    langfuse = pytest.importorskip("langfuse")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    tracer = LangfuseTracer(None)
    tracer._client = langfuse.Langfuse(
        public_key="TEST_FAKE_PUBLIC_ONLY", secret_key="TEST_FAKE_SECRET_ONLY", base_url="http://127.0.0.1:9",
        tracer_provider=provider, span_exporter=exporter, mask=tracer.mask)
    router, _ = make_router({GROQ: 503, GEMINI: {"answer": "Yes", "confidence": 0.9}}, tracer)
    router.register_secrets(["Zed Example"])
    result = await router.generate_json("screening_qa", "sys", "I am Zed Example", Reply)
    provider.force_flush()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"llm.screening_qa", "groq", "gemini"}
    assert result.trace_id and len(result.trace_id) == 32
    assert all(format(span.context.trace_id, "032x") == result.trace_id for span in spans.values())
    exported = json.dumps({name: dict(span.attributes) for name, span in spans.items()}, default=str)
    assert "Zed Example" not in exported
    assert "http_503" in exported and "gemini-" in exported.lower()


# --- judge -------------------------------------------------------------------------------------
def answerer(judge_reply, mode, tracer=None, generator=ANSWER):
    """Groq generates, Gemini judges (the judge chain starts with Gemini and excludes Groq)."""
    router, seen = make_router({GROQ: generator, GEMINI: judge_reply}, tracer)
    cache = SemanticCache(MemoryCacheStore(), DeterministicTestEmbedder())
    screening = ScreeningAnswerer(cache, router, judge=AnswerJudge(router, mode=mode))
    screening.bind_profile(SAFE_PROFILE)
    return screening, cache, seen


def test_judge_mode_parsing_defaults_to_shadow():
    assert judge_mode({}) == "shadow" and judge_mode({"AI_V2_JUDGE_MODE": "ENFORCE"}) == "enforce"
    assert judge_mode({"AI_V2_JUDGE_MODE": "nonsense"}) == "shadow"


async def test_shadow_mode_without_tracing_never_calls_the_judge():
    screening, _, seen = answerer({"supported": False, "score": 0.1, "reason": "x"}, "shadow")
    resolved = await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert resolved.answer == "Yes" and resolved.judge is None and seen == [GROQ]


async def test_enforce_rejection_sends_the_question_to_the_human_and_is_not_cached():
    tracer = RecordingTracer()
    screening, cache, seen = answerer({"supported": False, "score": 0.2, "reason": "not in profile"},
                                      "enforce", tracer)
    resolved = await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert resolved.answer is None and resolved.tier == 3
    assert resolved.reason == "llm_judge_rejected" and resolved.judge == "rejected"
    assert seen == [GROQ, GEMINI]
    assert await cache.lookup("screening_qa", QUESTION) is None
    assert tracer.named("judge_supported")[0][:3] == ("trace-1", "judge_supported", False)
    assert tracer.named("answer_accepted")[0][:3] == ("trace-1", "answer_accepted", False)


async def test_shadow_rejection_keeps_the_answer_but_does_not_cache_it():
    tracer = RecordingTracer()
    screening, cache, _ = answerer({"supported": False, "score": 0.2, "reason": "not in profile"},
                                   "shadow", tracer)
    resolved = await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert resolved.answer == "Yes" and resolved.judge == "rejected" and not resolved.cached_new
    assert await cache.lookup("screening_qa", QUESTION) is None
    assert tracer.named("answer_accepted")[0][2] is True


async def test_approved_answer_is_used_cached_and_scored():
    tracer = RecordingTracer()
    screening, _, _ = answerer({"supported": True, "score": 0.95, "reason": "matches profile"},
                                   "enforce", tracer)
    resolved = await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert resolved.answer == "Yes" and resolved.judge == "approved" and resolved.cached_new
    assert resolved.trace_id == "trace-1"
    assert tracer.named("judge_score")[0][2] == 0.95
    assert tracer.named("llm_confidence")[0][2] == 0.95


async def test_supported_but_low_score_counts_as_rejected():
    screening, _, _ = answerer({"supported": True, "score": 0.4, "reason": "unsure"}, "enforce",
                               RecordingTracer())
    assert (await screening.resolve(QUESTION, ("Yes", "No"), FACTS)).reason == "llm_judge_rejected"


async def test_judge_unavailable_fails_open():
    tracer = RecordingTracer()
    screening, _, seen = answerer(503, "enforce", tracer)
    resolved = await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert resolved.answer == "Yes" and resolved.judge is None and resolved.reason == "llm_accepted"
    assert seen == [GROQ, GEMINI]
    assert tracer.named("judge_available")[0][2] is False


async def test_judge_sees_the_proposed_answer_and_never_runs_on_the_generator_family():
    bodies: list[str] = []

    def judge(request):
        bodies.append(request.content.decode())
        return {"supported": True, "score": 0.9, "reason": "ok"}

    screening, _, seen = answerer(judge, "enforce", RecordingTracer())
    await screening.resolve(QUESTION, ("Yes", "No"), FACTS)
    assert seen == [GROQ, GEMINI] and "proposed_answer" in bodies[0] and "rotational shifts" in bodies[0]
