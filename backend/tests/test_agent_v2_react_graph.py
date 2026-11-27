"""Phase 9C LLM-first ReAct agent: read -> write -> final, the 4-step limit, malformed steps,
all-429 deterministic fallback (+ rate-limited provider note), PII placeholder round trip and
the LLM never seeing OTP codes or HITL answers (scripted router; no network)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from backend.app.agent_v2 import chat as chat_module
from backend.app.agent_v2.chat import HITL_MARKER
from backend.app.agent_v2.control_graph import ControlAgent
from backend.app.agent_v2.tools import PendingConfirmations
from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.router import AllLLMProvidersExhaustedError
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import agent_chat_key
from backend.tests.agent_v2_fakes import (
    NOW,
    ScriptedRouter,
    agent,
    cache,
    final,
    store_with_profile,
    tool,
)
from backend.tests.test_telegram_v2_bot import waiting_job

KEY = agent_chat_key("telegram", 4242)



@pytest.fixture(autouse=True)
def _fresh_fallback_note_window():
    """chat._last_note is a process-wide hourly rate limit; another test file's fallback must not
    hide this file's "invalid steps twice" notice (order-dependent failure in the full suite)."""
    chat_module._last_note.clear()
    yield
    chat_module._last_note.clear()

async def chat(bot, text, key=KEY):
    return await bot.run_chat(text, chat_key=key, source="telegram")


async def test_read_then_write_then_final_with_code_rendered_changes():
    store = store_with_profile()
    router = ScriptedRouter([tool("get_portal_rules", portal="naukri"),
                             tool("update_portal_rule", portals=["naukri"], patch={"max_applies_per_day": 60}),
                             final("Raised <b>Naukri</b> to 60/day.")])
    result = await chat(agent(store, router), "naukri is too slow, make it 60 a day")
    assert result["mode"] == "llm" and result["ok"] and result["tools"] == ["get_portal_rules", "update_portal_rule"]
    assert (await store.get_rules("naukri")).max_applies_per_day == 60
    assert result["reply_html"].startswith("Raised &lt;b&gt;Naukri&lt;/b&gt; to 60/day.")  # LLM prose escaped
    assert "<b>Portal rules updated</b>" in result["reply_html"] and "50 → 60" in result["reply_html"]
    assert [p[0] for p in router.prompts] == ["agent_react"] * 3
    assert '"tool":"get_portal_rules"' in router.prompts[1][2] and 'daily_cap\\":50' in router.prompts[1][2]
    assert [e.outcome for e in store.agent_audit] == ["ok"]  # reads are not audited, the write is
    turns = await store.recent_turns(KEY)
    assert [t.role for t in turns] == ["user", "assistant"] and "60 a day" in turns[0].content


async def test_step_limit_stops_after_four_tool_steps():
    store = store_with_profile()
    router = ScriptedRouter([tool("get_system_status")] * 5)
    result = await chat(agent(store, router), "loop forever")
    assert result["tools"] == ["get_system_status"] * 4 and "stopped after 4 tool steps" in result["reply"]
    assert len(router.prompts) == 5 and router.steps == []


async def test_malformed_steps_twice_fall_back_to_the_deterministic_parser():
    store = store_with_profile()
    router = ScriptedRouter([{"action": "tool"}, {"action": "tool", "tool_name": ""}])
    result = await chat(agent(store, router), "raise naukri daily limit to 70")
    assert result["mode"] == "deterministic" and result["tool"] == "update_portal_rule" and result["ok"]
    assert (await store.get_rules("naukri")).max_applies_per_day == 70
    assert "invalid steps twice" in result["reply_html"] and len(router.prompts) == 2


async def test_unknown_tool_from_the_llm_is_refused_audited_and_observed():
    store = store_with_profile()
    router = ScriptedRouter([tool("send_email", to="hr@acme.com"), final("I can't send email.")])
    result = await chat(agent(store, router), "email the recruiter")
    assert result["verdict"] == "rejected" and "never send email" in router.prompts[1][2]
    assert store.agent_audit[-1].outcome == "refused"


async def test_all_providers_429_fall_back_with_a_rate_limited_provider_note():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"retry-after": "30"}, json={"error": "rate"})

    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                         env={"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY"}, transport=httpx.MockTransport(handler))
    store = store_with_profile()
    clock = {"now": NOW}
    bot = ControlAgent(store, ai=ai, clock=lambda: clock["now"], pending=PendingConfirmations())
    key = agent_chat_key("telegram", 777)
    first = await chat(bot, "raise naukri daily limit to 65", key)
    assert first["mode"] == "deterministic" and (await store.get_rules("naukri")).max_applies_per_day == 65
    assert "groq: http_429" in first["reply_html"] and len(requests) == 1  # fallback never re-sends to an LLM
    second = await chat(bot, "pause", key)
    assert second["ok"] and "groq" not in second["reply_html"]  # note at most once per hour
    puzzled = await chat(bot, "hmm what about the weather", key)
    assert "built-in command parser" in puzzled["reply_html"]  # not understood: always explained
    clock["now"] += timedelta(hours=1, minutes=1)
    assert "built-in command parser" in (await chat(bot, "resume", key))["reply_html"]


async def test_exhausted_router_falls_back_and_no_provider_configured_too():
    store = store_with_profile()
    router = ScriptedRouter([AllLLMProvidersExhaustedError("agent_react", [
        {"provider": "groq", "outcome": "http_429"}, {"provider": "gemini", "outcome": "unconfigured"}])])
    result = await chat(agent(store, router), "how many applied today?", agent_chat_key("telegram", 31337))
    assert result["mode"] == "deterministic" and "groq: http_429" in result["reply_html"]
    assert "gemini" not in result["reply_html"]
    offline = await chat(agent(store_with_profile(), None), "status", agent_chat_key("api", "x"))
    assert offline["mode"] == "deterministic" and "no LLM provider is configured" in offline["reply_html"]


async def test_pii_placeholders_round_trip_to_tool_args_but_never_reach_the_llm():
    store = store_with_profile()
    semantic = cache()
    router = ScriptedRouter([tool("upsert_qa_fact", question="What is your alternate phone number?",
                                  answer="[PHONE_1] / [EMAIL_1]"), final("Saved [PHONE_1].")])
    result = await chat(agent(store, router, semantic=semantic),
                        "remember my alternate number +91 98765 43210 and mail me at owner.alt@gmail.com")
    hit = await semantic.lookup("screening_qa", "What is your alternate phone number?")
    assert hit is not None
    assert hit.entry.answer_text == "+91 98765 43210 / owner.alt@gmail.com" and hit.entry.source == "user"
    seen = router.seen()
    assert "98765" not in seen and "owner.alt" not in seen and "[PHONE_1]" in seen and "[EMAIL_1]" in seen
    assert "98111" not in seen and "owner.example" not in seen  # profile contact data never in the prompt
    assert result["reply"].startswith("Saved +91 98765 43210")  # restored locally for the owner
    memory = " ".join(t.content for t in await store.recent_turns(KEY))
    assert "98765" not in memory and "owner.alt" not in memory
    assert "98765" not in str(store.agent_audit)


async def test_llm_never_sees_otp_codes_or_hitl_answers():
    store = store_with_profile()
    _, question = await waiting_job(store, 1)
    _, otp = await waiting_job(store, 2, kind="OTP", prompt="Naukri needs OTP", options=())
    await store.mark_hitl_delivered(otp.id, 900)
    router = ScriptedRouter([tool("resolve_hitl_via_agent", hitl_id_or_ref=otp.ref, answer="[CODE_1]"),
                             final("Sent [CODE_1] to the worker."),
                             tool("resolve_hitl_via_agent", hitl_id_or_ref=question.ref, answer="Yes"),
                             final("Answered."),
                             final("Nothing else is open.")])
    bot = agent(store, router)
    first = await chat(bot, "the otp is 482913")
    assert (await store.get_hitl(otp.id)).answer_text == "482913"
    assert first["reply"].startswith("Sent 482913")  # restored only in the owner's own chat
    assert first["hitl_resolutions"] and first["hitl_resolutions"][0].hitl.id == otp.id
    await chat(bot, "yes I can relocate to Pune")
    assert (await store.get_hitl(question.id)).answer_text == "Yes"
    await chat(bot, "anything else open?")
    seen = router.seen()
    assert "482913" not in seen and "[CODE_1]" in seen
    last = router.prompts[-1][2]
    assert '"open_requests":[]' in last and "relocate to Pune" not in last  # HITL answers never in memory
    contents = [t.content for t in await store.recent_turns(KEY)]
    assert contents.count(HITL_MARKER) == 2 and not any("482913" in c for c in contents)
    assert (await store.get_application(question.application_id)).state is S.SCORED


async def test_typing_confirm_confirms_the_latest_pending_write():
    store = store_with_profile()
    router = ScriptedRouter([tool("update_portal_rule", portals=["naukri"], patch={"auto_apply_enabled": True}),
                             final("Tap confirm to enable live auto-apply.")])
    bot = agent(store, router)
    asked = await chat(bot, "turn on auto apply for naukri")
    assert asked["verdict"] == "confirm" and asked["confirmation"]["token"] and len(router.prompts) == 1
    assert not (await store.get_rules("naukri")).auto_apply_enabled and "Confirm" in asked["reply_html"]
    done = await chat(bot, "confirm")
    assert done["ok"] and done["mode"] == "confirmation" and (await store.get_rules("naukri")).auto_apply_enabled
    assert len(router.prompts) == 1  # "confirm" never goes to the LLM
    assert [e.outcome for e in store.agent_audit] == ["needs_confirmation", "ok"]
