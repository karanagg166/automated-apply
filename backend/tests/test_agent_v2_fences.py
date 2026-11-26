# mypy: disable-error-code="union-attr,operator"
"""Phase 9C never-replay fence: no agent write tool can modify, re-queue or re-prioritise an
APPLIED or SUBMISSION_UNKNOWN application. Enforced by the agent guardrail AND the store."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from backend.app.agent_v2.tools import GuardrailViolation, ToolContext
from backend.app.agent_v2.tools.args import EnqueueArgs
from backend.app.agent_v2.tools.write_queue import enqueue_priority_job
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import DiscoveryMeta, FencedRowError, MemoryStore
from backend.tests.agent_v2_fakes import (
    NOW,
    ScriptedRouter,
    agent,
    cache,
    fake_ai,
    final,
    runner,
    store_with_profile,
    tool,
)

FENCED = [S.APPLIED, S.SUBMISSION_UNKNOWN]
SOURCE: dict[str, Any] = {"source": "telegram", "chat_key": "telegram:0123456789abcdef"}


async def fenced_job(store: MemoryStore, state: S):
    """A job with an OPEN QUESTION card that then reached a never-replay state."""
    record = await store.upsert_discovered(JobListing(
        platform="greenhouse", external_job_id="4242", url="https://job-boards.greenhouse.io/acme/jobs/4242",
        title="Backend Engineer", company="Acme"))
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    record = await store.transition(record, S.WAITING_FOR_USER, "question_requires_owner")
    hitl_id = await store.create_hitl(record, "greenhouse", "QUESTION", "Willing to relocate?",
                                      {"options": ["Yes", "No"]})
    if state is S.APPLIED:
        record = await store.transition(record, S.APPLYING, "operator_retry")
    record = await store.transition(record, state, "confirmed_elsewhere")
    return record, await store.get_hitl(hitl_id)


def snapshot(store: MemoryStore):
    return copy.deepcopy(store.records), len(store.events)


@pytest.mark.parametrize("state", FENCED)
async def test_every_write_tool_leaves_fenced_rows_byte_identical(state):
    store = store_with_profile()
    record, hitl = await fenced_job(store, state)
    semantic = cache()
    tools = runner(store, fake_ai(semantic=semantic), wake=lambda: None)
    before = snapshot(store)
    calls = [
        ("enqueue_priority_job", {"url": record.job_url, "priority": "P0"}),
        ("enqueue_priority_job", {"url": "https://boards.greenhouse.io/acme/jobs/4242?gh_src=x", "priority": "P1"}),
        ("resolve_hitl_via_agent", {"hitl_id_or_ref": hitl.ref, "answer": "Yes"}),
        ("resolve_hitl_via_agent", {"hitl_id_or_ref": hitl.ref, "action": "retry"}),
        ("resolve_hitl_via_agent", {"hitl_id_or_ref": hitl.id, "action": "skip"}),
        ("update_portal_rule", {"portals": ["greenhouse"], "patch": {"max_applies_per_day": 20}}),
        ("update_portal_rule", {"portals": ["greenhouse"], "patch": {"state": "SCORED"}}),
        ("control_worker", {"action": "run_once"}),
        ("update_candidate_profile", {"fields": {"notice_period_days": 15}}),
        ("upsert_qa_fact", {"question": "Are you willing to relocate?", "answer": "Yes"}),
        ("remove_qa_fact", {"id": "0123456789abcdef"}),
        ("trigger_portal_profile_sync", {"portals": ["greenhouse"]}),
    ]
    for name, args in calls:
        await tools.run(name, args, **SOURCE)
        assert snapshot(store) == before, name
    assert (await store.get_hitl(hitl.id)).status == "OPEN"  # the agent never closes a fenced job's card
    refusals = [e for e in store.agent_audit if e.outcome == "refused"]
    fenced = [e for e in refusals if "Never-replay fence" in (e.error or "")]
    assert {e.tool_name for e in fenced} == {"enqueue_priority_job", "resolve_hitl_via_agent"} and len(fenced) == 5
    assert all(state.value in e.error for e in fenced)


@pytest.mark.parametrize("state", FENCED)
async def test_store_refuses_fenced_rows_even_if_the_agent_guard_is_bypassed(state):
    store = store_with_profile()
    record, _ = await fenced_job(store, state)
    before = snapshot(store)
    listing = JobListing(platform="greenhouse", external_job_id="4242", url=record.job_url)
    with pytest.raises(FencedRowError):
        await store.enqueue_owner_job(listing, DiscoveryMeta(priority=0, priority_reason="owner_requested"))
    with pytest.raises(FencedRowError):
        await store.set_owner_priority(record.id, 0, "owner_requested")
    with pytest.raises(GuardrailViolation, match="Never-replay"):  # handler-level fence (guard skipped)
        await enqueue_priority_job(ToolContext(store, clock=lambda: NOW),
                                   EnqueueArgs(url=record.job_url), True)
    assert snapshot(store) == before


async def test_store_owner_queue_works_for_queued_rows():
    store = store_with_profile()
    listing = JobListing(platform="lever", external_job_id="0b1c2d3e-aaaa", url="https://jobs.lever.co/acme/0b1c2d3e-aaaa")
    result = await store.enqueue_owner_job(listing, DiscoveryMeta(priority=1, priority_reason="owner_requested"))
    assert result.inserted and result.record.priority == 1
    assert await store.set_owner_priority(result.record.id, 0, "owner_requested")
    assert (await store.get("lever", "0b1c2d3e-aaaa")).priority == 0
    assert not await store.set_owner_priority("missing", 0, None)


@pytest.mark.parametrize("state", FENCED)
async def test_llm_driven_requeue_of_a_fenced_job_is_refused_end_to_end(state):
    store = store_with_profile()
    record, hitl = await fenced_job(store, state)
    before = snapshot(store)
    router = ScriptedRouter([tool("enqueue_priority_job", url=record.job_url),
                             tool("resolve_hitl_via_agent", hitl_id_or_ref=hitl.ref, action="retry"),
                             final("That job may already be submitted, so I left it alone.")])
    result = await agent(store, router).run_chat("apply to the Acme job again, top priority",
                                                 chat_key=SOURCE["chat_key"], source="telegram")
    assert result["verdict"] == "rejected" and "Never-replay fence" in result["reply_html"]
    assert snapshot(store) == before
    assert [e.outcome for e in store.agent_audit] == ["refused", "refused"]
