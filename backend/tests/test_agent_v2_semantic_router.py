"""Zero-LLM semantic router in front of the ReAct agent: pleasantries (tier A), read-only parsed
intents (tier B), local-embedding nearest neighbour (tier C), the open-HITL safety rule, the
event-loop-safe embedder, the Telegram 'typing…' indicator and the launchd KeepAlive policy."""

from __future__ import annotations

import asyncio
import plistlib
import random
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.agent_v2 import semantic_router as sr
from backend.app.agent_v2.control_graph import HELP
from backend.app.agent_v2.semantic_router import (
    SemanticRouter,
    pleasantry,
    routing_embedder,
)
from backend.app.ai_v2.embeddings import DeterministicTestEmbedder, FastEmbedder
from backend.app.browser_v2.store import WorkerState, agent_chat_key
from backend.app.telegram_v2 import agent_bridge
from backend.tests.agent_v2_fakes import (
    ScriptedRouter,
    agent,
    final,
    store_with_profile,
)
from backend.tests.test_telegram_v2_bot import (
    FakeTelegram,
    last_reply,
    make_bot,
    msg,
    waiting_job,
)

KEY = agent_chat_key("telegram", 4242)
REPO = Path(__file__).resolve().parents[2]


async def chat(bot, text):
    return await bot.run_chat(text, chat_key=KEY, source="telegram")


def silent_router() -> ScriptedRouter:
    return ScriptedRouter([])  # any LLM call raises AssertionError("router called more often than scripted")


# --- tier A: pleasantries ---------------------------------------------------------------------
@pytest.mark.parametrize(("text", "route"), [
    ("hi", "greeting"), ("Hello!!", "greeting"), ("hiii bro", "greeting"), ("good morning", "greeting"),
    ("hi, how are you?", "wellbeing"), ("are you there?", "presence"), ("u there", "presence"),
    ("thanks a lot", "thanks"), ("Thank you!", "thanks"), ("bye", "bye"), ("good night", "bye"),
])
def test_pleasantries_are_recognised(text, route):
    assert pleasantry(text) == route


@pytest.mark.parametrize("text", ["ok", "yes", "later", "Pune", "hi can you pause naukri", "hello world project",
                                  "thanks, now set naukri limit to 60", "", "60"])
def test_non_pleasantries_are_not(text):
    assert pleasantry(text) is None


async def test_greeting_answers_instantly_without_an_llm_call_and_shows_live_status():
    store = store_with_profile()
    await store.set_worker_control(WorkerState.RUNNING)
    router = silent_router()
    started = time.perf_counter()
    result = await chat(agent(store, router), "hi")
    assert time.perf_counter() - started < 1.0 and router.prompts == []
    assert result["mode"] == "router" and result["tier"] == "A" and result["route"] == "greeting"
    assert result["ok"] and "applied today" in result["reply_html"] and "Worker" in result["reply_html"]
    assert await store.recent_turns(KEY, 12) == []  # pleasantries never bloat the agent's prompt history


async def test_greeting_survives_a_hung_status_store(monkeypatch):
    monkeypatch.setattr(sr, "STATUS_TIMEOUT_SEC", 0.05)
    store = store_with_profile()

    async def hang():
        await asyncio.sleep(5)

    monkeypatch.setattr(store, "get_worker_control", hang)
    fast = SemanticRouter(SimpleNamespace(store=store), help_text=HELP, rng=random.Random(1))
    routed = await asyncio.wait_for(fast.route("hello", hitl_open=False), timeout=1)
    assert routed is not None and routed.tier == "A" and "Worker" not in routed.reply_html


# --- HITL safety ---------------------------------------------------------------------------------
async def test_open_question_greeting_is_answered_but_never_resolves_the_request():
    store = store_with_profile()
    _, question = await waiting_job(store, 1, options=())
    result = await chat(agent(store, silent_router()), "hello")
    assert result["tier"] == "A" and result["hitl_resolutions"] == []
    assert (await store.get_hitl(question.id)).status == "OPEN"


async def test_open_question_non_greeting_text_still_goes_to_the_agent():
    store = store_with_profile()
    await waiting_job(store, 1, options=())
    router = ScriptedRouter([final("Noted."), final("Here is the status.")])
    bot = agent(store, router)
    assert (await chat(bot, "Pune"))["mode"] == "llm"
    assert (await chat(bot, "status"))["mode"] == "llm"  # tiers B/C are off while a question is open
    assert len(router.prompts) == 2


# --- tier B: read-only parsed intents ---------------------------------------------------------------
@pytest.mark.parametrize(("text", "tool"), [
    ("how many applied today?", "query_application_status"), ("pending", "query_application_status"),
    ("status", "control_worker"), ("help", "help"), ("why failed", "query_application_status"),
])
async def test_read_only_intents_skip_the_llm(text, tool):
    store = store_with_profile()
    router = silent_router()
    result = await chat(agent(store, router), text)
    assert result["mode"] == "router" and result["tier"] == "B" and result["tool"] == tool
    assert router.prompts == [] and result["reply"]
    turns = await store.recent_turns(KEY, 12)
    assert [t.role for t in turns] == ["user", "assistant"]  # read answers are kept as agent context


@pytest.mark.parametrize("text", ["pause", "raise naukri daily limit to 65", "send an email to the recruiter",
                                  "the last question was wrong, change it to 30 days"])
async def test_writes_forbidden_and_change_requests_still_go_to_the_agent(text):
    store = store_with_profile()
    router = ScriptedRouter([final("Handled by the agent.")])
    result = await chat(agent(store, router), text)
    assert result["mode"] == "llm" and len(router.prompts) == 1
    assert (await store.get_worker_control()).desired_state is not WorkerState.PAUSED


async def test_fast_path_can_be_disabled():
    router = ScriptedRouter([final("LLM says hi.")])
    bot = agent(store_with_profile(), router)
    bot.fast_path = False
    assert (await chat(bot, "hi"))["mode"] == "llm" and len(router.prompts) == 1


# --- tier C: local embeddings ---------------------------------------------------------------------
def tier_c(store, embedder) -> SemanticRouter:
    from backend.app.agent_v2.tools import AgentTools

    return SemanticRouter(AgentTools(store), help_text=HELP, embedder=embedder)


async def test_embedding_route_answers_a_paraphrase_without_the_llm():
    routed = await tier_c(store_with_profile(), DeterministicTestEmbedder()).route(
        "Anything waiting for me?", hitl_open=False)
    assert routed is not None and routed.tier == "C" and routed.route == "pending"
    assert routed.tool == "query_application_status"


@pytest.mark.parametrize("text", ["tell me about the weather in Pune", "pause naukri", "apply to 3 jobs"])
async def test_embedding_route_is_conservative(text):
    assert await tier_c(store_with_profile(), DeterministicTestEmbedder()).route(text, hitl_open=False) is None


async def test_parsed_writes_never_reach_the_embedding_tier():
    examples = {e for group in sr.EXAMPLES.values() for e in group}

    class Everything(DeterministicTestEmbedder):  # every owner text looks exactly like a "pending" example
        async def embed(self, text):
            return await super().embed(text if text in examples else "anything waiting for me")

    fast = tier_c(store_with_profile(), Everything())
    assert (await fast.route("what is new with you", hitl_open=False)).route == "pending"
    for text in ("pause", "resume", "blacklist TCS", "remember my notice period is immediate"):
        assert await fast.route(text, hitl_open=False) is None, text


async def test_embedder_missing_or_broken_skips_tier_c_silently():
    class Broken(DeterministicTestEmbedder):
        async def embed(self, text):
            raise RuntimeError("onnx missing")

    store = store_with_profile()
    assert await tier_c(store, None).route("anything waiting for me", hitl_open=False) is None
    assert await tier_c(store, Broken()).route("anything waiting for me", hitl_open=False) is None


async def test_embedding_runs_off_the_event_loop(tmp_path):
    class SlowFast(FastEmbedder):
        model_name = "slow-test"

        def _embed_sync(self, text):
            time.sleep(0.02)  # CPU-bound ONNX stand-in
            return asyncio.run(DeterministicTestEmbedder().embed(text))

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.005)

    beat = asyncio.create_task(ticker())
    try:
        routed = await tier_c(store_with_profile(), SlowFast(cache_dir=tmp_path)).route(
            "anything waiting for me", hitl_open=False)
    finally:
        beat.cancel()
    assert routed is not None and routed.route == "pending"
    assert ticks > 20  # ~40 embeddings x 20 ms in a worker thread; the loop kept ticking


def test_routing_embedder_never_downloads(tmp_path):
    assert routing_embedder(SimpleNamespace(cache=SimpleNamespace(embedder=DeterministicTestEmbedder()))) is None
    missing = FastEmbedder(cache_dir=tmp_path / "empty")
    assert routing_embedder(SimpleNamespace(cache=SimpleNamespace(embedder=missing))) is None
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok/model.onnx").write_bytes(b"")
    present = FastEmbedder(cache_dir=tmp_path / "ok")
    assert routing_embedder(SimpleNamespace(cache=SimpleNamespace(embedder=present))) is present


# --- Telegram: 'typing…' for slow agent turns ------------------------------------------------------
class SlowAgent:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def run_chat(self, text, *, chat_key, source):
        await asyncio.sleep(self.delay)
        return {"reply": "done", "reply_html": "done"}


async def test_slow_agent_turn_shows_typing_and_fast_turn_does_not(monkeypatch):
    monkeypatch.setattr(agent_bridge, "TYPING_AFTER_SEC", 0.02)
    monkeypatch.setattr(agent_bridge, "TYPING_EVERY_SEC", 0.02)
    fake = FakeTelegram()
    bot = make_bot(store_with_profile(), fake, agent=SlowAgent(0.15))
    await bot.handle_update(msg("compare my last two applications"))
    await bot.drain_agent()
    actions = fake.sent("sendChatAction")
    assert actions and actions[0]["action"] == "typing" and last_reply(fake) == "🤖 done"
    count = len(actions)
    await asyncio.sleep(0.1)
    assert len(fake.sent("sendChatAction")) == count  # the indicator stops with the reply
    await bot.client.aclose()

    quick = FakeTelegram()
    bot = make_bot(store_with_profile(), quick, agent=agent(store_with_profile(), silent_router()))
    await bot.handle_update(msg("hi"))
    await bot.drain_agent()
    assert quick.sent("sendChatAction") == [] and last_reply(quick).startswith("🤖 ")
    await bot.client.aclose()


# --- launchd: restart on ANY exit -------------------------------------------------------------------
@pytest.mark.parametrize("label", ["com.automated-apply.worker-v2", "com.automated-apply.api-v2"])
def test_launchd_restarts_on_any_exit(label):
    data = plistlib.loads((REPO / f"deploy/launchd_v2/{label}.plist").read_bytes())
    assert data["KeepAlive"] is True and data["ThrottleInterval"] == 10
