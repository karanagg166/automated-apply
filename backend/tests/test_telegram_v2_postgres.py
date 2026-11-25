"""Phase 4 on a disposable PostgreSQL 17 with migration 004 applied.

telegram_v2_state offset persistence across restarts, hitl_requests delivery /
conditional close / ref + reply lookups, WAITING_FOR_USER -> SCORED priority
re-queue with append-only events, and the serialized single connection shared
by the worker loop and the Telegram poller.
"""

import asyncio
import os

import httpx
import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.hitl import HITLResolutionService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import PostgresStore, SerializedConnection
from backend.app.telegram_v2.bot import TelegramBot
from backend.app.telegram_v2.config import TelegramConfig
from backend.tests.test_browser_v2_postgres_store import database  # noqa: F401 - module fixture
from backend.tests.test_v2_migration_sql import PG_BIN

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")
TOKEN = "123456789:TEST_FAKE_TOKEN_ONLY_abcdefghijklmnop"


@pytest_asyncio.fixture
async def store(database):  # noqa: F811
    import asyncpg

    connection = await asyncpg.connect(database)
    await connection.execute(
        "TRUNCATE public.application_state_events, public.hitl_requests, public.applications CASCADE")
    await connection.execute("UPDATE public.telegram_v2_state SET last_update_id=NULL, polling_state='stopped'")
    await connection.execute("UPDATE public.portal_rules SET auth_status='UNKNOWN'")
    yield PostgresStore(SerializedConnection(connection))
    await connection.close()


async def waiting(store, i=1, kind="QUESTION", prompt="Willing to relocate to Pune?"):
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"pg-{i}",
                                                      url=f"https://example.com/{i}", title="Python Developer",
                                                      company="Initech"))
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    record = await store.transition(record, S.WAITING_FOR_USER, "question_requires_owner")
    hitl_id = await store.create_hitl(record, "naukri", kind, prompt, {"options": ["Yes", "No"]})
    return record, hitl_id


async def test_telegram_state_and_offset_survive_restart(store, database):  # noqa: F811
    import asyncpg

    with pytest.raises(ValueError):
        await store.update_telegram_state(polling_state="bogus")
    state = await store.update_telegram_state(last_update_id=812, polling_state="conflict",
                                              last_error="x" * 900)
    assert state.last_update_id == 812 and len(state.last_error) == 500
    fresh = await asyncpg.connect(database)  # restarted worker process
    try:
        restarted = await (await PostgresStore.borrowed(fresh)).get_telegram_state()
    finally:
        await fresh.close()
    assert restarted.last_update_id == 812 and restarted.polling_state == "conflict"


async def test_hitl_delivery_lookup_close_and_requeue(store):
    record, hitl_id = await waiting(store, 1)
    _, other_id = await waiting(store, 2)
    assert [h.id for h in await store.undelivered_hitl()] == [hitl_id, other_id]
    await store.mark_hitl_delivered(hitl_id, 5001)
    await store.mark_hitl_delivered(hitl_id, 9999)  # never overwritten (no double-send bookkeeping)
    assert [h.id for h in await store.undelivered_hitl()] == [other_id]
    by_message = await store.find_hitl_by_message(5001)
    assert by_message.id == hitl_id and by_message.company == "Initech" and by_message.options == ("Yes", "No")
    assert [h.id for h in await store.find_open_hitl_by_ref(by_message.ref)] == [hitl_id]
    assert await store.find_open_hitl_by_ref("zz'; DROP") == []
    page, total = await store.list_hitl("OPEN", "naukri")
    assert total == 2 and page[0].application_state == "WAITING_FOR_USER"

    resolver = HITLResolutionService(store)
    result = await resolver.answer(hitl_id, "1", via="telegram")
    assert result.ok and result.answer == "Yes" and result.requeued
    assert await store.close_hitl(hitl_id, "ANSWERED", "No", "dashboard") is None  # conditional on OPEN
    row = await store.get_hitl(hitl_id)
    assert row.status == "ANSWERED" and row.answer_text == "Yes" and row.resolved_via == "telegram"
    app = await store.get_application(record.id)
    assert app.state is S.SCORED and app.retry_after is not None
    events = await store.application_events(record.id)
    assert events[-1]["event_type"] == "hitl_resolved_requeued" and events[-1]["payload"]["hitl_id"] == hitl_id
    assert [r.id for r in await store.requeued_applications("naukri")] == [record.id]
    assert await store.hitl_answers(record.id) == {"Willing to relocate to Pune?": "Yes"}
    assert await store.mark_hitl_consumed(record.id) == 1
    assert await store.requeued_applications("naukri") == []
    assert await store.count_open_hitl() == 1


async def test_skip_resume_and_never_replay_on_postgres(store):
    record, hitl_id = await waiting(store, 3)
    applied = await store.transition(await store.get_application(record.id), S.SUBMISSION_UNKNOWN, "ambiguous")
    resolver = HITLResolutionService(store)
    result = await resolver.answer(hitl_id, "Yes", via="dashboard")
    assert result.ok and not result.requeued and result.application_state == "SUBMISSION_UNKNOWN"
    assert (await store.get_application(applied.id)).state is S.SUBMISSION_UNKNOWN
    _skip_record, skip_id = await waiting(store, 4)
    assert (await resolver.skip(skip_id, via="telegram")).application_state == "FILTERED_OUT"
    await store.record_auth("naukri", "AUTH_REQUIRED")
    await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    outcome = await resolver.resume_portal("naukri", via="telegram")
    assert outcome.ok and len(outcome.resolved) == 1
    assert (await store.get_rules("naukri")).auth_status == "UNKNOWN"


async def test_serialized_connection_shares_one_connection_between_worker_and_poller(store):
    """Worker transitions (transactions) + poller writes concurrently on one asyncpg connection."""
    records = [(await waiting(store, 10 + i))[0] for i in range(5)]

    async def worker_side():
        for record in records:
            current = await store.get_application(record.id)
            await store.transition(current, S.FILTERED_OUT, "concurrency_probe")

    async def poller_side():
        for i in range(30):
            await store.update_telegram_state(last_update_id=1000 + i, polling_state="polling")
            await store.count_open_hitl()

    await asyncio.wait_for(asyncio.gather(worker_side(), poller_side()), timeout=20)
    assert (await store.get_telegram_state()).last_update_id == 1029
    states = [(await store.get_application(r.id)).state for r in records]
    assert states == [S.FILTERED_OUT] * len(records)


async def test_bot_poll_persists_offset_in_postgres(store):
    def api(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 77, "message": {"message_id": 1, "chat": {"id": 4242}, "from": {"id": 4242},
                                              "text": "/pause"}}]})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 3}})

    config = TelegramConfig.from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_OWNER_CHAT_ID": "4242"})
    bot = TelegramBot(config, store, transport=httpx.MockTransport(api), min_send_interval=0)
    assert await bot.poll_once() == 0
    state = await store.get_telegram_state()
    assert state.last_update_id == 77 and state.polling_state == "polling" and state.last_poll_at is not None
    assert (await store.get_worker_control()).desired_state.value == "PAUSED"
    await bot.client.aclose()
