"""Timings must include pool contention without retaining SQL or business data."""
import asyncio

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.agent.store import memory_row
from backend.app.core.timing import (
    RequestTimingMiddleware,
    TimedAsyncAdaptedQueuePool,
    instrument_engine,
    trace,
)


@pytest.mark.asyncio
async def test_parent_owner_lock_is_reused_but_rolled_back_child_lock_is_not(db_session):
    await memory_row(db_session, lock=True)
    await db_session.commit()
    await memory_row(db_session, lock=True)
    queries = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)
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
        assert len(queries) == 1 and queries[0].startswith("SELECT")
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_existing_owner_memory_never_requires_an_initialization_write(db_session):
    from backend.app.agent.store import MEMORY_KEY
    from backend.app.dashboard.models import OwnerPreference

    row = OwnerPreference(key=MEMORY_KEY, value={"preserved": "fictional"})
    db_session.add(row)
    await db_session.commit()
    queries = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        found = await memory_row(db_session, lock=True)
        assert found.value == {"preserved": "fictional"}
        assert len(queries) == 1 and queries[0].startswith("SELECT")
        await memory_row(db_session, lock=True)
        assert len(queries) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_pool_wait_and_occupancy_are_measured_separately(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fixture.db", poolclass=TimedAsyncAdaptedQueuePool, pool_size=1, max_overflow=0)
    instrument_engine(engine)
    factory = async_sessionmaker(engine)
    current = {"request_id": "fixture", "stages": {}}
    token = trace.set(current)
    async def blocked():
        async with factory() as session:
            await session.execute(text("SELECT 'private-value'"))
    try:
        async with factory() as holder:
            await holder.connection()
            work = asyncio.create_task(blocked())
            await asyncio.sleep(.05)
        await work
        stages = current["stages"]
        assert stages["pool_acquisition"]["seconds"] >= .04
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


@pytest.mark.asyncio
async def test_no_sql_transaction_uses_no_connection_and_implicit_flush_is_measured(tmp_path):
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.db.session import TimedSession
    from backend.app.models.base import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/flush.db",
                                 poolclass=TimedAsyncAdaptedQueuePool,
                                 pool_size=1, max_overflow=0)
    instrument_engine(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=TimedSession, expire_on_commit=False)
    current = {"request_id": "fixture-flush", "stages": {}}
    token = trace.set(current)
    try:
        async with factory() as session:
            await session.commit()
        assert "pool_acquisition" not in current["stages"]
        assert "connection_occupancy" not in current["stages"]
        async with factory() as session:
            session.add(OwnerPreference(key="fixture-timing", value={"fictional": True}))
            await session.flush()
            await session.execute(text("SELECT 1"))
            await session.commit()
        assert current["stages"]["pool_acquisition"]["count"] == 1
        assert current["stages"]["connection_occupancy"]["count"] == 1
        assert current["stages"]["sql_write"]["count"] == 1
    finally:
        trace.reset(token)
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_pool_wait_is_measured_without_phantom_checkout(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/cancel.db",
                                 poolclass=TimedAsyncAdaptedQueuePool,
                                 pool_size=1, max_overflow=0)
    instrument_engine(engine)
    factory = async_sessionmaker(engine)
    current = {"request_id": "fixture-cancel", "stages": {}}
    async def queued():
        token = trace.set(current)
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        finally:
            trace.reset(token)
    try:
        async with factory() as holder:
            await holder.connection()
            task = asyncio.create_task(queued())
            await asyncio.sleep(.03)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert engine.pool.checkedout() == 1
        assert engine.pool.checkedout() == 0
        assert current["stages"]["pool_acquisition"]["seconds"] >= .02
        assert "connection_occupancy" not in current["stages"]
        async with factory() as recovered:
            assert await recovered.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()
