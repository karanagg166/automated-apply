"""Timings must include pool contention without retaining SQL or business data."""
import asyncio

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.agent.store import memory_row
from backend.app.core.timing import (
    RequestTimingMiddleware,
    instrument_engine,
    span,
    trace,
)


@pytest.mark.asyncio
async def test_parent_owner_lock_is_reused_but_rolled_back_child_lock_is_not(db_session):
    await memory_row(db_session, lock=True)
    queries = []
    def observe(*args):
        queries.append(1)
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        async with db_session.begin_nested():
            await memory_row(db_session, lock=True)
        # Only SAVEPOINT/RELEASE; no INSERT/SELECT for the already-held owner lock.
        assert not queries  # SQLAlchemy lazily opens savepoints when SQL is needed.
        await db_session.rollback()
        async with db_session.begin_nested() as child:
            await memory_row(db_session, lock=True)
            await child.rollback()
        queries.clear()
        await memory_row(db_session, lock=True)
        assert len(queries) >= 2
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_pool_wait_and_occupancy_are_measured_separately(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fixture.db", pool_size=1, max_overflow=0)
    instrument_engine(engine)
    factory = async_sessionmaker(engine)
    current = {"request_id": "fixture", "stages": {}}
    token = trace.set(current)
    async def blocked():
        async with factory() as session:
            with span("pool_checkout_wait"):
                await session.connection()
            await session.execute(text("SELECT 'private-value'"))
    try:
        async with factory() as holder:
            await holder.connection()
            work = asyncio.create_task(blocked())
            await asyncio.sleep(.05)
        await work
        stages = current["stages"]
        assert stages["pool_checkout_wait"]["seconds"] >= .04
        assert stages["connection_occupancy"]["count"] == 2
        assert "private-value" not in str(current)
    finally:
        trace.reset(token)
        await engine.dispose()


@pytest.mark.asyncio
async def test_timing_covers_response_body_and_resets_context(monkeypatch):
    captured = []
    monkeypatch.setattr("backend.app.core.timing.emit", captured.append)
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(.02)
        await send({"type": "http.response.body", "body": b"ok"})
    async def send(message):
        pass
    await RequestTimingMiddleware(app)({"type": "http"}, None, send)
    assert captured[0]["http_seconds"] >= .02
    assert captured[0]["response_start_seconds"] < captured[0]["http_seconds"]
    assert trace.get() is None
