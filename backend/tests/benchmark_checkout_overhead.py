"""Explicit isolated checkout comparison against approved SHA; run with pytest -s."""
import asyncio
import json
import subprocess
import sys
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.timing import TimedAsyncAdaptedQueuePool, instrument_engine, trace
from backend.app.db import session as database


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["approved_eager", "corrected_lazy"])
async def test_pre_sql_work_does_not_speculatively_occupy_the_pool(tmp_path, monkeypatch, variant):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/checkout.db",
                                 poolclass=TimedAsyncAdaptedQueuePool,
                                 pool_size=1, max_overflow=0)
    instrument_engine(engine)
    factory = async_sessionmaker(engine)
    module = database
    if variant == "approved_eager":
        name = "approved_checkout_benchmark"
        module = ModuleType(name)
        sys.modules[name] = module
        source = subprocess.check_output([
            "git", "show", "d504d26e889859b2b39111bb5deedce80c4bd589:backend/app/db/session.py"
        ], text=True)
        exec(compile(source, "approved-session.py", "exec"), module.__dict__)
    monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    current = {"request_id": "fixture-" + variant, "stages": {}}
    peer = {"request_id": "fixture-peer-" + variant, "stages": {}}
    token = trace.set(current)
    dependency = module.get_db_session()
    try:
        session = await anext(dependency)
        occupied_before_sql = engine.pool.checkedout()
        async def status_read():
            peer_token = trace.set(peer)
            try:
                async with factory() as other:
                    assert await other.scalar(text("SELECT 1")) == 1
            finally:
                trace.reset(peer_token)
        pending = asyncio.create_task(status_read())
        # Controlled pre-SQL asynchronous work; this is a fixture, not a live stage attribution.
        await asyncio.sleep(.05)
        peer_finished_before_sql = pending.done()
        assert await session.scalar(text("SELECT 1")) == 1
        with pytest.raises(StopAsyncIteration):
            await anext(dependency)
        await pending
        print(json.dumps({"fixture": "checkout_overhead", "variant": variant,
                          "pre_sql_delay_seconds": .05,
                          "occupied_before_sql": occupied_before_sql,
                          "peer_finished_before_sql": peer_finished_before_sql,
                          "request_trace": current, "peer_trace": peer}))
        assert occupied_before_sql == (1 if variant == "approved_eager" else 0)
        assert peer_finished_before_sql == (variant == "corrected_lazy")
        assert engine.pool.checkedout() == 0
    finally:
        await dependency.aclose()
        trace.reset(token)
        await engine.dispose()
