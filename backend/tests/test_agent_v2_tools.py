# mypy: disable-error-code="union-attr,operator"
"""Phase 9C audited agent tools: every tool's happy path, Pydantic validation and audit rows
(no network, no LLM: the AuditedToolRunner is driven directly)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from backend.app.agent_v2.prompts import system_prompt
from backend.app.agent_v2.tools import (
    TOOL_REGISTRY,
    WRITE_TOOL_NAMES,
    AgentTools,
    catalog,
)
from backend.app.ai_v2.router import MAX_SYSTEM_PROMPT_CHARS
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import WorkerState
from backend.tests.agent_v2_fakes import (
    NOW,
    cache,
    fake_ai,
    job,
    runner,
    store_with_profile,
)
from backend.tests.test_telegram_v2_bot import waiting_job

SOURCE: dict[str, Any] = {"source": "telegram", "chat_key": "telegram:0123456789abcdef"}


def audits(store, tool_name=None):
    return [e for e in store.agent_audit if tool_name is None or e.tool_name == tool_name]


def test_registry_has_no_forbidden_capability_and_fits_the_prompt():
    names = set(TOOL_REGISTRY)
    assert {"get_system_status", "query_applications", "get_application_details", "get_candidate_profile_and_facts",
            "search_semantic_cache", "get_portal_rules", "get_pending_hitl", "get_analytics_summary",
            "update_candidate_profile", "upsert_qa_fact", "remove_qa_fact", "update_portal_rule", "control_worker",
            "enqueue_priority_job", "resolve_hitl_via_agent", "trigger_portal_profile_sync"} == names
    for word in ("send", "mail", "deliver", "delete", "replay"):
        assert not [n for n in names if word in n]
        assert not [n for n in dir(AgentTools) if word in n and word != "mail"]
    assert len(catalog()) == 16 and len(system_prompt()) <= MAX_SYSTEM_PROMPT_CHARS


# --- READ tools -----------------------------------------------------------------------------------
async def test_read_tools_happy_path_and_reads_are_not_audited():
    store = store_with_profile()
    await job(store, 1, state=S.APPLIED, company="Acme Corp")
    await job(store, 2, state=S.FILTERED_OUT, company="Beta Labs")
    _, hitl = await waiting_job(store, 3)
    semantic = cache()
    await semantic.put("screening_qa", "What is your notice period?", "60 days", "user")
    tools = runner(store, fake_ai(semantic=semantic))
    status = await tools.run("get_system_status", {}, **SOURCE)
    assert status.ok and '"desired":"STOPPED"' in status.llm_summary and '"open_hitl":1' in status.llm_summary
    apps = await tools.run("query_applications", {"company": "acme", "days": 30}, **SOURCE)
    assert apps.ok and "Acme Corp" in apps.llm_summary and "Beta" not in apps.llm_summary
    applied = await tools.run("query_applications", {"status": "applied", "portal": "Greenhouse"}, **SOURCE)
    assert '"total":1' in applied.llm_summary
    details = await tools.run("get_application_details", {"app_id_or_company": "beta"}, **SOURCE)
    assert '"state":"FILTERED_OUT"' in details.llm_summary and '"history"' in details.llm_summary
    profile = await tools.run("get_candidate_profile_and_facts", {}, **SOURCE)
    assert "expected_ctc" in profile.user_html and "18" in profile.user_html  # owner sees his own values
    assert "98111" not in profile.llm_summary and "Karan" not in profile.llm_summary and "18" not in \
        profile.llm_summary.split('"facts_present"')[0]
    found = await tools.run("search_semantic_cache", {"query": "notice"}, **SOURCE)
    assert "60 days" in found.llm_summary
    rules = await tools.run("get_portal_rules", {"portal": "Naukri"}, **SOURCE)
    assert rules.ok and '"portal":"naukri"' in rules.llm_summary and "greenhouse" not in rules.llm_summary
    pending = await tools.run("get_pending_hitl", {}, **SOURCE)
    assert hitl.ref in pending.llm_summary and "relocate" in pending.llm_summary
    funnel = await tools.run("get_analytics_summary", {"days": 7}, **SOURCE)
    assert '"applied":1' in funnel.llm_summary and '"filtered":1' in funnel.llm_summary
    assert '"waiting":1' in funnel.llm_summary
    assert audits(store) == []


@pytest.mark.parametrize("name,args", [
    ("query_applications", {"limit": 26}),
    ("query_applications", {"days": 91}),
    ("get_analytics_summary", {"days": 0}),
    ("search_semantic_cache", {"query": "x", "limit": 11}),
    ("update_portal_rule", {"portals": ["naukri"], "patch": {}, "surprise": 1}),
    ("enqueue_priority_job", {"url": "http://insecure.example.com/job/1"}),
    ("control_worker", {"action": "explode"}),
])
async def test_invalid_arguments_are_refused_and_audited(name, args):
    store = store_with_profile()
    result = await runner(store).run(name, args, **SOURCE)
    assert not result.ok and result.outcome == "refused" and "Invalid" in result.message
    assert [e.outcome for e in audits(store, name)] == ["refused"]


async def test_unknown_or_forbidden_tool_is_refused_and_audited():
    store = store_with_profile()
    for name in ("send_email", "delete_application", "replay_job", "drop_tables"):
        result = await runner(store).run(name, {}, **SOURCE)
        assert result.outcome == "refused" and "never send email" in result.message
    assert {e.outcome for e in store.agent_audit} == {"refused"} and len(store.agent_audit) == 4


# --- WRITE tools -----------------------------------------------------------------------------------
async def test_update_candidate_profile_validates_and_reseeds_profile_facts():
    store = store_with_profile()
    semantic = cache()
    tools = runner(store, fake_ai(semantic=semantic))
    result = await tools.run("update_candidate_profile", {"fields": {
        "notice_period_days": 30, "company_blacklist": {"add": ["TCS"], "remove": ["wipro"]}}}, **SOURCE)
    assert result.ok and store.profile["preferences"]["notice_period_days"] == 30
    assert store.profile["preferences"]["company_blacklist"] == ["TCS"]
    assert "60 → 30" in result.user_html
    hit = await semantic.lookup("screening_qa", "What is your notice period (in days)?")
    assert hit is not None and hit.entry.answer_text == "30 days" and hit.entry.source == "profile"
    entry = audits(store, "update_candidate_profile")[-1]
    assert entry.outcome == "ok" and entry.before_summary["notice_period_days"] == 60
    assert entry.after_summary["notice_period_days"] == 30
    phone = await tools.run("update_candidate_profile", {"fields": {"phone": "+91 99999 00000"}}, **SOURCE)
    bad = await tools.run("update_candidate_profile", {"fields": {"notice_period_days": -5}}, **SOURCE)
    unknown = await tools.run("update_candidate_profile", {"fields": {"favourite_colour": "red"}}, **SOURCE)
    assert not phone.ok and "dashboard" in phone.message and not bad.ok and "validation" in bad.message
    assert not unknown.ok and store.profile["preferences"]["notice_period_days"] == 30
    assert [e.outcome for e in audits(store, "update_candidate_profile")] == ["ok", "refused", "refused", "refused"]
    assert "99999" not in str(store.agent_audit)


async def test_qa_facts_upsert_and_confirmed_removal():
    store = store_with_profile()
    semantic = cache()
    tools = runner(store, fake_ai(semantic=semantic))
    saved = await tools.run("upsert_qa_fact", {"question": "Are you open to night shifts?", "answer": "No"},
                            **SOURCE)
    hit = await semantic.lookup("screening_qa", "Are you open to night shifts?")
    assert saved.ok and hit.entry.source == "user" and hit.entry.answer_text == "No"
    blocked = await tools.run("upsert_qa_fact", {"question": "What is your Naukri password?", "answer": "x"},
                              **SOURCE)
    assert not blocked.ok and "never stored" in blocked.message
    asked = await tools.run("remove_qa_fact", {"id": hit.entry.id}, **SOURCE)
    assert asked.outcome == "needs_confirmation" and asked.token and (await semantic.stats())["total_entries"] == 1
    done = await tools.confirm(asked.token, chat_key=SOURCE["chat_key"], source="telegram")
    assert done.ok and (await semantic.stats())["total_entries"] == 0
    assert [e.outcome for e in audits(store, "remove_qa_fact")] == ["needs_confirmation", "ok"]
    assert audits(store, "remove_qa_fact")[-1].before_summary["question"] == "Are you open to night shifts?"


async def test_update_portal_rule_caps_boards_risk_and_forbidden_keys():
    store = store_with_profile()
    tools = runner(store)
    ok = await tools.run("update_portal_rule", {"portals": ["Naukri"], "patch": {"max_applies_per_day": 60}},
                         **SOURCE)
    assert ok.ok and (await store.get_rules("naukri")).max_applies_per_day == 60 and "50 → 60" in ok.user_html
    boards = await tools.run("update_portal_rule", {"portals": ["greenhouse"], "boards_add": ["Stripe", "figma"]},
                             **SOURCE)
    assert boards.ok and set(store.profile["preferences"]["greenhouse_boards"]) == {"stripe", "figma"}
    await tools.run("update_portal_rule", {"portals": ["greenhouse"], "boards_remove": ["figma"]}, **SOURCE)
    assert set(store.profile["preferences"]["greenhouse_boards"]) == {"stripe"}
    wrong = await tools.run("update_portal_rule", {"portals": ["naukri"], "boards_add": ["x"]}, **SOURCE)
    smuggled = await tools.run("update_portal_rule", {"portals": ["naukri"], "patch": {"auth_status": "OK"}}, **SOURCE)
    too_big = await tools.run("update_portal_rule", {"portals": ["naukri"], "patch": {"max_applies_per_day": 900}},
                              **SOURCE)
    assert not wrong.ok and not smuggled.ok and "can't be changed" in smuggled.message
    assert too_big.outcome == "needs_confirmation"  # >100/day asks first; validation then still applies
    refused = await tools.confirm(too_big.token, chat_key=SOURCE["chat_key"], source="telegram")
    assert not refused.ok and "500" in refused.message and (await store.get_rules("naukri")).max_applies_per_day == 60
    risky = await tools.run("update_portal_rule", {"portals": ["naukri"], "patch": {"auto_apply_enabled": True}},
                            **SOURCE)
    many = await tools.run("update_portal_rule", {"portals": ["naukri", "lever", "greenhouse", "ashby"],
                                                  "patch": {"max_job_age_days": 3}}, **SOURCE)
    assert risky.outcome == many.outcome == "needs_confirmation"
    assert not (await store.get_rules("naukri")).auto_apply_enabled
    cancelled = await tools.cancel(risky.token, chat_key=SOURCE["chat_key"], source="telegram")
    assert cancelled.ok and not (await store.get_rules("naukri")).auto_apply_enabled
    outcomes = [e.outcome for e in audits(store, "update_portal_rule")]
    assert outcomes == ["ok", "ok", "ok", "refused", "refused", "needs_confirmation", "refused",
                        "needs_confirmation", "needs_confirmation", "cancelled"]


async def test_control_worker_actions_dry_run_switch_and_wake():
    store = store_with_profile()
    woke = []
    tools = runner(store, wake=lambda: woke.append(1))
    assert (await tools.run("control_worker", {"action": "pause"}, **SOURCE)).ok
    assert (await store.get_worker_control()).desired_state is WorkerState.PAUSED
    assert (await tools.run("control_worker", {"action": "run_once"}, **SOURCE)).ok and woke == [1]
    sweep = await tools.run("control_worker", {"action": "sweep", "portal": "lever"}, **SOURCE)
    assert sweep.ok and woke == [1, 1] and "worker woken" in sweep.user_html
    portal = await tools.run("control_worker", {"action": "pause", "portal": "internshala"}, **SOURCE)
    assert portal.ok and (await store.get_rules("internshala")).paused_until == NOW + timedelta(hours=24)
    live = await tools.run("control_worker", {"action": "resume", "dry_run": False}, **SOURCE)
    assert live.outcome == "needs_confirmation" and (await store.get_worker_control()).dry_run
    assert (await tools.confirm(None, chat_key=SOURCE["chat_key"], source="telegram")).ok
    control = await store.get_worker_control()
    assert not control.dry_run and control.desired_state is WorkerState.RUNNING
    status = await tools.run("control_worker", {"action": "status"}, **SOURCE)
    assert status.ok and "LIVE" in status.llm_summary
    entry = audits(store, "control_worker")[-2]
    assert entry.outcome == "ok" and entry.before_summary["dry_run"] is True and entry.after_summary["dry_run"] is False


async def test_enqueue_priority_job_from_a_pasted_url():
    store = store_with_profile()
    woke = []
    tools = runner(store, wake=lambda: woke.append(1))
    result = await tools.run("enqueue_priority_job", {"url": "https://boards.greenhouse.io/stripe/jobs/7001"},
                             **SOURCE)
    record = await store.get("greenhouse", "7001")
    assert result.ok and record.priority == 0 and record.priority_reason == "owner_requested"
    assert record.discovered_via == "telegram" and record.state is S.DISCOVERED and woke == [1]
    assert "auto-apply is OFF" in result.user_html
    filtered = await job(store, 5, state=S.FILTERED_OUT)
    again = await tools.run("enqueue_priority_job", {"url": filtered.job_url, "priority": "P1"}, **SOURCE)
    moved = await store.get("greenhouse", filtered.external_job_id)
    assert again.ok and moved.state is S.SCORED and moved.priority == 1
    unknown = await tools.run("enqueue_priority_job", {"url": "https://example.org/careers/1"}, **SOURCE)
    assert not unknown.ok and "which portal" in unknown.message
    assert [e.outcome for e in audits(store, "enqueue_priority_job")] == ["ok", "ok", "refused"]


async def test_resolve_hitl_via_agent_answers_skips_and_redacts_audit():
    store = store_with_profile()
    semantic = cache()
    tools = runner(store, fake_ai(semantic=semantic))
    record, hitl = await waiting_job(store, 1)
    _, otp = await waiting_job(store, 2, kind="OTP", prompt="Naukri needs OTP", options=())
    answered = await tools.run("resolve_hitl_via_agent", {"hitl_id_or_ref": hitl.ref, "answer": "yes"}, **SOURCE)
    assert answered.ok and (await store.get_hitl(hitl.id)).answer_text == "Yes"
    assert (await store.get_application(record.id)).state is S.SCORED and answered.data["resolution"].ok
    code = await tools.run("resolve_hitl_via_agent", {"hitl_id_or_ref": otp.ref, "answer": "482913"}, **SOURCE)
    assert code.ok and (await store.get_hitl(otp.id)).answer_text == "482913"
    assert (await semantic.stats())["total_entries"] == 1  # the OTP is never cached
    assert "482913" not in str(store.agent_audit) and audits(store)[-1].args["answer"] == "[redacted]"
    missing = await tools.run("resolve_hitl_via_agent", {"hitl_id_or_ref": "abcdef"}, **SOURCE)
    assert not missing.ok and missing.outcome == "refused"


async def test_profile_sync_unavailable_dry_run_and_live_confirmation():
    store = store_with_profile()
    assert "not available yet" in (await runner(store).run(
        "trigger_portal_profile_sync", {"portals": ["naukri"]}, **SOURCE)).message

    class Sync:
        def __init__(self):
            self.calls = []

        async def sync(self, portals, *, dry_run, trigger):
            self.calls.append((portals, dry_run, trigger))
            return {p: {"status": "ok"} for p in portals}

    sync = Sync()
    tools = runner(store, profile_sync=sync)
    assert (await tools.run("trigger_portal_profile_sync", {"portals": ["naukri"]}, **SOURCE)).ok
    live = await tools.run("trigger_portal_profile_sync", {"portals": ["naukri"], "dry_run": False}, **SOURCE)
    assert live.outcome == "needs_confirmation" and sync.calls == [(["naukri"], True, "telegram")]
    assert (await tools.confirm(live.token, chat_key=SOURCE["chat_key"], source="telegram")).ok
    assert sync.calls[-1] == (["naukri"], False, "telegram")


async def test_confirmation_tokens_expire_after_ten_minutes_and_are_per_chat():
    store = store_with_profile()
    clock = {"now": NOW}
    tools = runner(store, clock=lambda: clock["now"])
    asked = await tools.run("update_portal_rule", {"portals": ["naukri"], "patch": {"auto_apply_enabled": True}},
                            **SOURCE)
    other = await tools.confirm(asked.token, chat_key="telegram:ffffffffffffffff", source="telegram")
    assert not other.ok  # another chat can't confirm it
    clock["now"] += timedelta(minutes=11)
    late = await tools.confirm(asked.token, chat_key=SOURCE["chat_key"], source="telegram")
    assert not late.ok and "expired" in late.message and not (await store.get_rules("naukri")).auto_apply_enabled
    assert audits(store)[-1].outcome == "cancelled" and audits(store)[-1].error == "confirmation_expired"
    assert WRITE_TOOL_NAMES >= {"update_portal_rule", "remove_qa_fact"}
