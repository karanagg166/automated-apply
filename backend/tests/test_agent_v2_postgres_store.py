"""Phase 9C PostgresStore parity (disposable local PostgreSQL + migrations 004 + 005): agent audit
log, conversation memory window, analytics funnel and the store-level never-replay fence."""

from __future__ import annotations

import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import (
    AuditEntry,
    ConversationTurn,
    DiscoveryMeta,
    FencedRowError,
    PostgresStore,
    agent_chat_key,
)
from backend.tests.test_browser_v2_postgres_store import database, pytestmark  # noqa: F401 - shared fixture

KEY = agent_chat_key("telegram", 4242)


@pytest_asyncio.fixture
async def store(database):  # noqa: F811 - the imported module-scoped fixture
    import asyncpg

    connection = await asyncpg.connect(database)
    await connection.execute(
        "TRUNCATE public.application_state_events, public.hitl_requests, public.mail_events, public.applications, "
        "public.agent_conversation_turns CASCADE")
    yield await PostgresStore.borrowed(connection)
    await connection.close()


async def test_audit_log_is_append_only_and_lists_newest_first(store):
    first = await store.append_audit(AuditEntry("telegram", "update_portal_rule", "ok", args={"portals": ["naukri"]},
                                                before_summary={"naukri": {"max_applies_per_day": 50}},
                                                after_summary={"naukri": {"max_applies_per_day": 60}}))
    await store.append_audit(AuditEntry("api", "remove_qa_fact", "needs_confirmation", error="x" * 900))
    assert first.id and first.created_at and first.after_summary == {"naukri": {"max_applies_per_day": 60}}
    rows = await store.list_audit(10)
    assert [r.tool_name for r in rows][:2] == ["remove_qa_fact", "update_portal_rule"]
    assert len(rows[0].error) == 500 and rows[1].args == {"portals": ["naukri"]}
    assert [r.tool_name for r in await store.list_audit(5, "remove_qa_fact")] == ["remove_qa_fact"]
    with pytest.raises(ValueError):
        AuditEntry("telegram", "Bad Name", "ok")


async def test_conversation_window_prunes_to_200_and_forget_clears(store):
    for i in range(205):
        await store.append_turn(ConversationTurn(KEY, "user" if i % 2 == 0 else "assistant", f"turn {i}"))
    other = agent_chat_key("api", "dashboard")
    await store.append_turn(ConversationTurn(other, "user", "hello"))
    count = await store.connection.fetchval(
        "SELECT count(*) FROM public.agent_conversation_turns WHERE chat_key = $1", KEY)
    assert count == 200
    recent = await store.recent_turns(KEY, 12)
    assert [t.content for t in recent] == [f"turn {i}" for i in range(193, 205)]
    assert await store.recent_turns("bad key") == []
    assert await store.clear_turns(KEY) == 200 and await store.recent_turns(KEY) == []
    assert [t.content for t in await store.recent_turns(other)] == ["hello"]


async def test_funnel_counts_per_platform_with_recruiter_replies(store):
    applied = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="n1", url="https://x/1",
                                                       company="Acme", title="Dev"))
    applied = await store.transition(applied, S.APPLYING, "apply_started")
    await store.transition(applied, S.APPLIED, "confirmed", receipt={"source": "test"})
    filtered = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="n2", url="https://x/2"))
    await store.transition(filtered, S.FILTERED_OUT, "posting_too_old")
    unknown = await store.upsert_discovered(JobListing(platform="lever", external_job_id="l1", url="https://x/3"))
    unknown = await store.transition(unknown, S.APPLYING, "apply_started")
    await store.transition(unknown, S.SUBMISSION_UNKNOWN, "navigation")
    await store.connection.execute(
        "INSERT INTO public.mail_events (message_key, kind, source, platform) VALUES ('m1', 'INTERVIEW', 'imap', "
        "'naukri'), ('m2', 'JOB_ALERT', 'imap', 'naukri')")
    funnel = await store.funnel(7)
    assert funnel["naukri"]["discovered"] == 2 and funnel["naukri"]["applied"] == 1
    assert funnel["naukri"]["filtered"] == 1 and funnel["naukri"]["recruiter_replies"] == 1
    assert funnel["lever"]["submission_unknown"] == 1 and funnel["lever"]["applied"] == 0
    assert set(await store.funnel(7, "lever")) == {"lever"}


@pytest.mark.parametrize("state", [S.APPLIED, S.SUBMISSION_UNKNOWN])
async def test_owner_queue_refuses_fenced_rows_in_sql(store, state):
    listing = JobListing(platform="greenhouse", external_job_id="77", url="https://job-boards.greenhouse.io/a/jobs/77")
    record = await store.upsert_discovered(listing)
    record = await store.transition(record, S.APPLYING, "apply_started")
    record = await store.transition(record, state, "done", receipt={"source": "test"} if state is S.APPLIED else None)
    before = await store.get("greenhouse", "77")
    with pytest.raises(FencedRowError):
        await store.enqueue_owner_job(listing, DiscoveryMeta(priority=0, priority_reason="owner_requested"))
    with pytest.raises(FencedRowError):
        await store.set_owner_priority(record.id, 0, "owner_requested")
    assert await store.get("greenhouse", "77") == before


async def test_owner_queue_inserts_and_retiers_queued_rows(store):
    listing = JobListing(platform="lever", external_job_id="0b1c2d3e-aaaa", url="https://jobs.lever.co/a/0b1c2d3e-aaaa")
    result = await store.enqueue_owner_job(listing, DiscoveryMeta(priority=1, priority_reason="owner_requested",
                                                                  discovered_via="telegram"))
    assert result.inserted and result.record.priority == 1 and result.record.discovered_via == "telegram"
    assert await store.set_owner_priority(result.record.id, 0, "owner_requested")
    assert (await store.get("lever", "0b1c2d3e-aaaa")).priority == 0
    assert not await store.set_owner_priority("00000000-0000-0000-0000-000000000000", 0, None)
