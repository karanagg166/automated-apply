"""Milestone 2 realtime ops stream: EventHub fan-out, DB-delta translation, slow-consumer resync /
eviction, Last-Event-ID replay, redaction, heartbeats, shutdown and the authenticated SSE route."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.api.v1.v2.routers.events import get_event_hub
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.events_v2.hub import EventHub, state_event_type
from backend.app.events_v2.sse import (
    HEARTBEAT,
    event_stream,
    format_event,
    parse_last_event_id,
)
from backend.app.main import app

BASE = "/api/v1/v2"


def memory_source(store):
    @asynccontextmanager
    async def source():
        yield store
    return source


async def drain(sub):
    items = []
    while not sub.queue.empty():
        items.append(sub.queue.get_nowait())
    return items


async def test_publish_fans_out_with_increasing_ids_and_scrubbed_payloads():
    hub = EventHub()
    first, second = hub.subscribe(), hub.subscribe()
    dsn = "postgresql://" + "user:" + "hunter2pass" + "@db.example/x"  # synthetic, split for secretlint
    event = await hub.publish("job.applied", {"company": "Acme", "otp": "123456", "session_token": "x",
                                              "detail": dsn})
    assert event.id == 1 and "otp" not in event.payload and "session_token" not in event.payload
    assert "hunter2pass" not in event.payload["detail"]
    for sub in (first, second):
        (got,) = await drain(sub)
        assert got.type == "job.applied" and got.payload["company"] == "Acme"
    with pytest.raises(ValueError):
        await hub.publish("not.a.type", {})


async def test_slow_consumer_gets_one_resync_then_is_evicted():
    hub = EventHub(queue_size=3, max_overflows=2)
    slow, fast = hub.subscribe(), hub.subscribe()
    for n in range(4):
        await hub.publish("job.queued", {"n": n})
        if n < 3:
            await drain(fast)
    items = await drain(slow)
    assert [i.type for i in items] == ["resync"] and slow.overflows == 1  # backlog dropped, never blocks
    for n in range(4):
        await hub.publish("job.queued", {"n": n})
    assert slow.evicted and slow not in hub.subscribers and hub.evictions == 1
    assert (await drain(slow))[-1] is None  # the stream ends; the browser reconnects fresh


async def test_last_event_id_replays_history_or_forces_resync():
    hub = EventHub(history=3)
    for n in range(5):
        await hub.publish("job.discovered", {"n": n})
    replay = await drain(hub.subscribe(last_event_id=3))
    assert [e.id for e in replay] == [4, 5]
    assert [e.type for e in await drain(hub.subscribe(last_event_id=1))] == ["resync"]  # older than history
    assert [e.type for e in await drain(hub.subscribe(last_event_id=99))] == ["resync"]  # other process lifetime
    assert parse_last_event_id("7") == 7 and parse_last_event_id("x") is None


def test_state_event_mapping():
    assert state_event_type({"to_state": "APPLIED"}) == "job.applied"
    assert state_event_type({"to_state": "APPLIED", "event_type": "verified_by_confirmation_email"}) \
        == "mail.reconciled"
    assert state_event_type({"to_state": "APPLYING"}) == "job.applying_step"
    assert state_event_type({"to_state": "FAILED", "event_type": "FAILED_TIMEOUT:pre_submit"}) == "job.failed"
    assert state_event_type({"to_state": "SCORED", "from_state": "DISCOVERED"}) == "job.queued"
    assert state_event_type({"to_state": "WAITING_FOR_USER"}) is None


async def test_poller_translates_store_deltas_once():
    store = MemoryStore()
    now = [datetime.now(UTC)]
    hub = EventHub(memory_source(store), clock=lambda: now[0], poll_interval=3600)
    sub = hub.subscribe()
    await hub.poll_once()  # baseline: worker row / breakers are not news
    assert await drain(sub) == []
    record = await store.upsert_discovered(JobListing(platform="lever", external_job_id="j1", url="https://x.example",
                                                      title="Backend Engineer", company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters")
    await store.transition(record, S.APPLYING, "apply_started")
    await store.create_hitl(record, "lever", "OTP", "Enter the code 482913", {})
    await store.record_circuit("lever", failures=3, level=1, open_until=now[0] + timedelta(minutes=5),
                               reason="DOM_CHANGED")
    from backend.app.browser_v2.store import WorkerState
    await store.set_worker_control(WorkerState.RUNNING, dry_run=False)
    await hub.poll_once()
    events = await drain(sub)
    kinds = [e.type for e in events]
    assert kinds[:2] == ["job.queued", "job.applying_step"]
    assert {"hitl.created", "worker.state", "portal.breaker_changed"} <= set(kinds)
    hitl = next(e for e in events if e.type == "hitl.created")
    assert hitl.payload["kind"] == "OTP" and hitl.payload["prompt"] is None  # OTP prompts never stream
    applying = next(e for e in events if e.type == "job.applying_step")
    assert applying.payload["company"] == "Acme" and applying.payload["step"] == "apply_started"
    await hub.poll_once()
    assert await drain(sub) == []  # overlap window re-read is deduplicated by id
    await hub.close()


async def test_poll_errors_never_raise():
    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    hub = EventHub(broken)
    assert await hub.poll_once() == 0 and hub.poll_errors == 1


async def test_stream_heartbeat_frames_disconnect_and_shutdown():
    hub = EventHub()
    sub = hub.subscribe()
    ticks = iter([0.0, 0.0, 0.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0])
    disconnected = [False]

    async def gone():
        return disconnected[0]

    stream = event_stream(hub, sub, heartbeat_sec=15, max_seconds=75, check_every=0.01, is_disconnected=gone,
                          monotonic=lambda: next(ticks, 20.0))
    assert await stream.__anext__() == "retry: 3000\n\n"
    assert await stream.__anext__() == HEARTBEAT
    event = await hub.publish("job.applied", {"company": "Acme"})
    frame = await stream.__anext__()
    assert frame == format_event(event) and frame.startswith(f"id: {event.id}\nevent: job.applied\ndata: ")
    disconnected[0] = True
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    assert sub not in hub.subscribers  # client abort unsubscribes

    sub2 = hub.subscribe()
    stream2 = event_stream(hub, sub2, max_seconds=75, check_every=0.01)
    await stream2.__anext__()
    await hub.close()
    with pytest.raises(StopAsyncIteration):
        await stream2.__anext__()


async def test_stream_self_closes_after_max_seconds():
    hub = EventHub()
    frames = [f async for f in event_stream(hub, hub.subscribe(), max_seconds=0.05, check_every=0.01)]
    assert frames == ["retry: 3000\n\n"] and not hub.subscribers


async def test_sse_route_requires_bearer_and_streams_replay(async_client, phase2_auth):
    hub = EventHub()
    await hub.publish("job.applied", {"company": "Acme"})
    app.dependency_overrides[get_event_hub] = lambda: hub
    try:
        denied = await async_client.get(f"{BASE}/events/stream", headers={"Authorization": "Bearer wrong"})
        assert denied.status_code == 401

        async def shut():
            await asyncio.sleep(0.2)
            await hub.close()

        closer = asyncio.create_task(shut())
        response = await async_client.get(f"{BASE}/events/stream", headers={**phase2_auth, "Last-Event-ID": "0"})
        await closer
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-transform" in response.headers["cache-control"]
        assert "event: job.applied" in response.text and '"company":"Acme"' in response.text
    finally:
        app.dependency_overrides.pop(get_event_hub, None)
