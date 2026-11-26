"""Phase 6A LangGraph control agent: intent parsing, guardrailed tools, LLM fallback and the
non-interrupting Telegram free-chat route."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.agent_v2 import intent as intents
from backend.app.agent_v2.control_graph import ControlAgent
from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerState
from backend.app.mail_v2.reader import MailEvent, MailEventStore
from backend.tests.test_telegram_v2_bot import (
    FakeTelegram,
    last_reply,
    make_bot,
    msg,
    waiting_job,
)

NOW = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)


def store_with_profile():
    return MemoryStore(profile={"preferences": {"target_roles": ["Backend Engineer"], "company_blacklist": ["Wipro"]},
                                "verified_skills": [{"name": "Python"}]})


def agent(store=None, **kw):
    return ControlAgent(store or store_with_profile(), clock=lambda: NOW, **kw)


@pytest.mark.parametrize("text,tool,args", [
    ("raise Naukri daily limit to 60", "update_portal_rule",
     {"platforms": ["naukri"], "changes": {"max_applies_per_day": 60}}),
    ("set instahyre hourly cap to 4", "update_portal_rule",
     {"platforms": ["instahyre"], "changes": {"max_applies_per_hour": 4}}),
    ("enable Instahyre", "update_portal_rule", {"platforms": ["instahyre"], "changes": {"enabled": True}}),
    ("turn off auto-apply on wellfound", "update_portal_rule",
     {"platforms": ["wellfound"], "changes": {"auto_apply_enabled": False}}),
    ("set max job age to 5 days", "update_portal_rule", {"platforms": ["*"], "changes": {"max_job_age_days": 5}}),
    ("blacklist TCS and Infosys", "update_preferences",
     {"op": "add", "key": "company_blacklist", "values": ["TCS", "Infosys"]}),
    ("set expected CTC to 18 LPA", "update_preferences", {"op": "set", "key": "expected_ctc", "value": 18}),
    ("add FastAPI to required keywords", "update_preferences",
     {"op": "add", "key": "keywords_required", "values": ["FastAPI"]}),
    ("my notice period is 2 months", "update_preferences", {"op": "set", "key": "notice_period_days", "value": 60}),
    ("why did you skip Razorpay?", "query_application_status", {"kind": "why", "company": "Razorpay"}),
    ("how many applied today?", "query_application_status", {"kind": "counts", "platform": None}),
    ("show last 5 drafts", "query_application_status", {"kind": "drafts", "limit": 5, "platform": None}),
    ("remember my notice period is immediate", "teach_semantic_cache",
     {"question": "What is your notice period?", "answer": "immediate"}),
    ("pause", "control_worker", {"action": "pause"}),
    ("resume", "control_worker", {"action": "resume"}),
    ("run once", "control_worker", {"action": "run_once"}),
    ("status", "control_worker", {"action": "status"}),
])
def test_deterministic_intent_parser(text, tool, args):
    parsed = intents.parse(text, now=NOW)
    assert parsed is not None and parsed.tool == tool and parsed.source == "deterministic"
    assert parsed.args == args


def test_pause_portal_for_hours_is_a_timestamp_and_answers_are_not_commands():
    parsed = intents.parse("pause Internshala for 3 hours", now=NOW)
    assert parsed.args["changes"] == {"paused_until": NOW + timedelta(hours=3)}
    assert intents.parse("resume internshala", now=NOW).args["changes"] == {"paused_until": None}
    for answer in ("Yes", "482913", "30 days", "Immediately", "No, I need 2 weeks"):
        parsed = intents.parse(answer, now=NOW)
        assert parsed is None or parsed.tool in ("help",), (answer, parsed)


@pytest.mark.parametrize("text,reason", [
    ("send the draft to the recruiter", "READ + DRAFT ONLY"),
    ("please email the recruiter at Acme", "READ + DRAFT ONLY"),
    ("delete all applications", "can't delete"),
    ("wipe the semantic cache", "can't delete"),
    ("reapply to the Razorpay job", "Never-replay"),
    ("retry the applied job at Acme", "Never-replay"),
])
async def test_guardrails_refuse_send_delete_and_replay(text, reason):
    store = store_with_profile()
    result = await agent(store).run(text)
    assert result["tool"] == "forbidden" and result["verdict"] == "rejected" and not result["ok"]
    assert reason in result["reply"] and "⛔" in result["reply"]
    assert (await store.get_rules("naukri")).revision == 1  # nothing changed


async def test_rule_updates_use_dashboard_validation_and_confirmation():
    store = store_with_profile()
    bot = agent(store)
    ok = await bot.run("raise Naukri daily limit to 60")
    assert ok["ok"] and (await store.get_rules("naukri")).max_applies_per_day == 60
    too_big = await bot.run("set naukri daily limit to 900")
    assert too_big["verdict"] == "rejected" and "less than or equal to 500" in too_big["reply"]
    crossed = await bot.run("set naukri hourly limit to 80")
    assert crossed["verdict"] == "rejected" and "hourly cap cannot exceed" in crossed["reply"]
    risky = await bot.run("enable auto apply on naukri")
    assert risky["verdict"] == "confirm" and not (await store.get_rules("naukri")).auto_apply_enabled
    confirmed = await bot.run("enable auto apply on naukri, confirm")
    assert confirmed["ok"] and (await store.get_rules("naukri")).auto_apply_enabled
    wide = await bot.run("set max job age to 5 days")
    assert wide["verdict"] == "confirm"  # every portal at once needs a confirm
    assert (await bot.run("set max job age to 5 days confirm"))["ok"]
    assert {r.max_job_age_days for r in await store.list_rules()} == {5}
    paused = await bot.run("pause Internshala for 3 hours")
    assert paused["ok"] and (await store.get_rules("internshala")).paused_until == NOW + timedelta(hours=3)


async def test_state_receipts_and_auth_cannot_be_changed_from_chat():
    store = store_with_profile()
    bot = agent(store)
    state = {"plan": {"tool": "update_portal_rule", "args": {"platforms": ["naukri"],
                                                            "changes": {"auth_status": "OK"}},
                      "source": "llm", "confirmed": True}}
    verdict = await bot.validate_guardrails(state)
    assert verdict["verdict"] == "rejected" and "can't be changed" in verdict["message"]


async def test_preferences_blacklist_add_remove_and_validation():
    store = store_with_profile()
    bot = agent(store)
    assert (await bot.run("blacklist TCS and Infosys"))["ok"]
    assert store.profile["preferences"]["company_blacklist"] == ["Wipro", "TCS", "Infosys"]
    assert (await bot.run("remove TCS from blacklist"))["ok"]
    assert store.profile["preferences"]["company_blacklist"] == ["Wipro", "Infosys"]
    assert (await bot.run("set expected CTC to 18 LPA"))["ok"] and store.profile["preferences"]["expected_ctc"] == 18
    bad = await bot.run("set expected ctc to 5000")
    assert bad["verdict"] == "ok" and not bad["ok"] and "invalid_preferences" in bad["reply"]
    assert store.profile["preferences"]["expected_ctc"] == 18


async def test_status_queries_explain_skips_and_count_today():
    store = store_with_profile()
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="r1", url="https://x/1",
                                                      title="SDE II", company="Razorpay Software Pvt Ltd"))
    await store.transition(record, S.FILTERED_OUT, "posting_too_old")
    applied = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="a1", url="https://x/2",
                                                       title="Backend Engineer", company="Acme"))
    applied = await store.transition(applied, S.APPLYING, "apply_started")
    await store.transition(applied, S.APPLIED, "confirmed", receipt={"source": "test"})
    bot = ControlAgent(store)  # real clock: "today" must include the APPLIED row just written
    why = await bot.run("why did you skip Razorpay?")
    assert "FILTERED_OUT" in why["reply"] and "posting_too_old" in why["reply"]
    counts = await bot.run("how many applied today?")
    assert "Naukri: 1/50 today" in counts["reply"]
    events = MailEventStore()
    await events.add(MailEvent("m1", "INTERVIEW", "imap", "hr@acme.example.com", "Interview next week", None, NOW,
                               company_name="Acme"))
    replies = await ControlAgent(store, mail_events=events).run("show last 5 replies")
    assert "Interview" in replies["reply"] and "Acme" in replies["reply"]


async def test_teach_semantic_cache_and_worker_control():
    store = store_with_profile()
    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(), env={})
    bot = agent(store, ai=ai)
    taught = await bot.run("remember my notice period is immediate")
    assert taught["ok"] and "Remembered" in taught["reply"]
    hit = await ai.cache.lookup("screening_qa", "What is your notice period?")
    assert hit is not None and hit.entry.answer_text == "immediate" and hit.entry.source == "user"
    assert (await bot.run("pause"))["ok"] and (await store.get_worker_control()).desired_state is WorkerState.PAUSED
    assert (await bot.run("run once"))["ok"] and (await store.get_worker_control()).run_once_requested_at
    assert "desired=PAUSED" in (await bot.run("status"))["reply"]


async def test_llm_fallback_only_proposes_and_is_still_validated():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        text = json.dumps({"tool": "update_portal_rule", "platforms": ["lever"],
                           "rule_changes": {"max_applies_per_day": 7, "auth_status": "OK"}, "confidence": 0.9})
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                         env={"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY"}, transport=httpx.MockTransport(handler))
    store = store_with_profile()
    result = await agent(store, ai=ai).run("could you make lever a bit calmer, like seven per day")
    assert calls and result["source"] == "llm" and result["verdict"] == "rejected"  # auth_status smuggled in
    assert (await store.get_rules("lever")).max_applies_per_day == 50
    offline = await agent(store_with_profile()).run("could you make lever calmer")
    assert offline["tool"] == "help" and "didn't understand" in offline["reply"]


# --- Telegram free-chat routing -------------------------------------------------------------------------
async def test_telegram_free_chat_goes_to_agent_without_blocking_an_in_flight_job():
    store = store_with_profile()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    in_flight = asyncio.Event()
    release = asyncio.Event()
    progress = []

    async def browser_job():  # stands in for an application being filled in Brave
        in_flight.set()
        await release.wait()
        progress.append("submitted")

    job = asyncio.create_task(browser_job())
    await in_flight.wait()
    await bot.handle_update(msg("raise Naukri daily limit to 60"))
    await bot.drain_agent()
    assert "Updated Naukri" in last_reply(fake) and (await store.get_rules("naukri")).max_applies_per_day == 60
    assert not job.done() and progress == []  # the agent never touched / paused the in-flight job
    release.set()
    await job
    assert progress == ["submitted"]


async def test_pending_hitl_query_lists_open_requests():
    store = store_with_profile()
    _, hitl = await waiting_job(store)
    result = await agent(store).run("show pending questions")
    assert result["ok"] and hitl.ref in result["reply"] and "relocate" in result["reply"]


async def test_telegram_plain_text_goes_to_the_agent_and_offline_answers_the_single_question():
    """Phase 9C: plain text goes to the agent. Offline, a control command is handled by the deterministic
    parser and never answers the open request; a plain reply with exactly one open QUESTION answers it."""
    store = store_with_profile()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    record, hitl = await waiting_job(store)
    await bot.handle_update(msg("pause"))  # clearly a control command: handled by the deterministic fallback
    await bot.drain_agent()
    assert (await store.get_hitl(hitl.id)).status == "OPEN"
    assert (await store.get_worker_control()).desired_state is WorkerState.PAUSED and "🤖" in last_reply(fake)
    await bot.handle_update(msg("thanks"))  # chit-chat never answers
    await bot.drain_agent()
    assert (await store.get_hitl(hitl.id)).status == "OPEN"
    await bot.handle_update(msg("Yes"))
    await bot.drain_agent()
    assert (await store.get_hitl(hitl.id)).status == "ANSWERED"
    assert (await store.get_application(record.id)).state is S.SCORED


async def test_telegram_ask_command_and_refusal():
    store = store_with_profile()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    await bot.handle_update(msg("/ask send all drafts to recruiters"))
    await bot.drain_agent()
    assert "READ + DRAFT ONLY" in last_reply(fake)
    await bot.handle_update(msg("/ask"))
    await bot.drain_agent()
    assert "Usage" in last_reply(fake)
