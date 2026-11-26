"""Phase 8 control agent: every owner command works deterministically with 0 LLM keys and
when every free provider returns 429, and the agent never blocks an in-flight apply."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.app.agent_v2 import intent as intents
from backend.app.agent_v2.control_graph import ControlAgent
from backend.app.ai_v2.router import AllLLMProvidersExhaustedError
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import (
    Decision,
    PortalRules,
    evaluate_job,
    parse_applicants,
)
from backend.app.browser_v2.schemas import PortalRulesPatch, PortalRulesRead
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerState

NOW = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


class ExhaustedRouter:
    any_configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def generate_json(self, *args, **kwargs):
        self.calls += 1
        raise AllLLMProvidersExhaustedError("agent_intent", [{"provider": "groq", "status": 429}])

    async def status(self):
        return []


def store_with_profile() -> MemoryStore:
    return MemoryStore(profile={"preferences": {"target_roles": ["Backend Engineer"]}, "verified_skills": []})


def agent(store=None, ai=None) -> ControlAgent:
    return ControlAgent(store or store_with_profile(), ai=ai, clock=lambda: NOW)


@pytest.mark.parametrize("text,tool,args", [
    ("status", "control_worker", {"action": "status"}),
    ("pause", "control_worker", {"action": "pause"}),
    ("resume", "control_worker", {"action": "resume"}),
    ("enable naukri", "update_portal_rule", {"platforms": ["naukri"], "changes": {"enabled": True}}),
    ("disable instahyre", "update_portal_rule", {"platforms": ["instahyre"], "changes": {"enabled": False}}),
    ("set naukri limit 60", "update_portal_rule", {"platforms": ["naukri"], "changes": {"max_applies_per_day": 60}}),
    ("set instahyre allow_unknown_age true", "update_portal_rule",
     {"platforms": ["instahyre"], "changes": {"allow_unknown_posting_age": True}}),
    ("set wellfound allow_unknown_age false", "update_portal_rule",
     {"platforms": ["wellfound"], "changes": {"allow_unknown_posting_age": False}}),
    ("block unknown posting dates on yc", "update_portal_rule",
     {"platforms": ["work_at_a_startup"], "changes": {"allow_unknown_posting_age": False}}),
    ("why failed", "query_application_status", {"kind": "failed", "limit": 5, "platform": None}),
    ("pending", "query_application_status", {"kind": "hitl", "limit": 10}),
    ("digest", "query_application_status", {"kind": "digest"}),
])
def test_deterministic_commands_parse_without_any_llm(text, tool, args):
    parsed = intents.parse(text, now=NOW)
    assert parsed is not None and parsed.tool == tool and parsed.source == "deterministic"
    assert parsed.args == args


def test_portal_pause_and_resume_parse():
    paused = intents.parse("pause naukri", now=NOW)
    assert paused is not None and paused.args["platforms"] == ["naukri"]
    assert paused.args["changes"]["paused_until"] > NOW
    resumed = intents.parse("resume naukri", now=NOW)
    assert resumed is not None and resumed.args["changes"] == {"paused_until": None}


@pytest.mark.parametrize("router", [None, ExhaustedRouter()], ids=["zero_keys", "all_429"])
async def test_every_command_executes_with_no_keys_or_all_providers_429(router):
    store = store_with_profile()
    ai = SimpleNamespace(router=router, cache=None) if router is not None else None
    control = agent(store, ai=ai)
    result = await control.run("set naukri limit 60")
    assert result["ok"] and (await store.get_rules("naukri")).max_applies_per_day == 60
    result = await control.run("set instahyre allow_unknown_age false")
    assert result["ok"] and (await store.get_rules("instahyre")).unknown_age_allowed is False
    assert (await control.run("pause"))["ok"] and (await store.get_worker_control()).desired_state is WorkerState.PAUSED
    assert (await control.run("resume"))["ok"]
    assert (await store.get_worker_control()).desired_state is WorkerState.RUNNING
    assert (await control.run("pending"))["reply"].startswith("✅ Nothing is waiting")
    digest = await control.run("digest")
    assert digest["ok"] and "Daily digest" in digest["reply"]
    # an unknown sentence degrades to help, never an exception
    unknown = await control.run("tell me a joke about kubernetes")
    assert unknown["verdict"] == "help" and "I didn't understand" in unknown["reply"]
    if isinstance(router, ExhaustedRouter):
        assert router.calls == 1  # only the unknown sentence reached the LLM tier


async def test_why_failed_lists_failed_and_unknown_with_reasons():
    store = store_with_profile()
    for i, (state, reason) in enumerate([(S.FAILED, "apply_control_changed"),
                                         (S.SUBMISSION_UNKNOWN, "confirmation_ambiguous")]):
        record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"f{i}",
                                                          url=f"https://example.com/{i}", title="SDE",
                                                          company=f"Co{i}"))
        record = await store.transition(record, S.APPLYING, "apply_started")
        await store.transition(record, state, reason)
    reply = (await agent(store).run("why failed"))["reply"]
    assert "apply_control_changed" in reply and "confirmation_ambiguous" in reply


async def test_agent_never_waits_for_an_in_flight_application():
    store = store_with_profile()
    browser_busy = asyncio.Event()
    release = asyncio.Event()

    async def in_flight_apply():
        browser_busy.set()
        await release.wait()  # e.g. Naukri chatbot questionnaire in progress

    apply_task = asyncio.create_task(in_flight_apply())
    await browser_busy.wait()
    result = await asyncio.wait_for(agent(store).run("disable naukri"), timeout=2)
    assert result["ok"] and not apply_task.done()  # rule changed; the apply is untouched
    release.set()
    await apply_task


def test_allow_unknown_posting_age_defaults_and_rules_engine():
    unknown = parse_applicants(None)
    instahyre = PortalRules(platform="instahyre", enabled=True)
    naukri = PortalRules(platform="naukri", enabled=True)
    assert instahyre.unknown_age_allowed is True and naukri.unknown_age_allowed is False
    assert evaluate_job(age_days=None, applicants=unknown, rules=naukri).decision is Decision.REVIEW
    allowed = evaluate_job(age_days=None, applicants=unknown, rules=instahyre)
    assert allowed.decision is Decision.PASS and "posting_age_unknown_allowed" in allowed.reasons
    # an explicit override wins either way; applicants are still enforced
    strict = PortalRules(platform="instahyre", enabled=True, allow_unknown_posting_age=False)
    assert evaluate_job(age_days=None, applicants=unknown, rules=strict).decision is Decision.REVIEW
    crowded = PortalRules(platform="naukri", enabled=True, allow_unknown_posting_age=True, max_applicants=10)
    assert evaluate_job(age_days=None, applicants=parse_applicants("500 applicants"),
                        rules=crowded).decision is Decision.FILTERED
    read = PortalRulesRead.from_rules(instahyre)
    assert read.allow_unknown_posting_age is True and read.allow_unknown_posting_age_default is True
    patch = PortalRulesPatch.model_validate({"revision": 1, "allow_unknown_posting_age": False})
    assert patch.changes() == {"allow_unknown_posting_age": False}
    with pytest.raises(ValueError):
        PortalRulesPatch.model_validate({"revision": 1, "allow_unknown_posting_age": "yes"})
