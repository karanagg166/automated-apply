"""Explicit fictional RTT benchmark; never connects to owner data. Run with pytest -s."""

import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import event

from backend.app.agent import store
from backend.app.browser import chrome_profiles, service
from backend.app.core.timing import instrument_engine, trace
from backend.tests.test_extension_tasks import browser_target as browser_target_fixture
from backend.tests.test_extension_tasks import inspect_task, opened

browser_target = browser_target_fixture


def original(path):
    name = "benchmark_" + Path(path).stem
    module = ModuleType(name)
    sys.modules[name] = module
    source = subprocess.check_output(
        ["git", "show", "c9890845be596a5f78bf7e0253b528639c1a9cb9:" + path], text=True
    )
    exec(compile(source, path, "exec"), module.__dict__)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["before", "after"])
async def test_roundtrips(db_session, browser_target, monkeypatch, variant):
    job, packet, _ = browser_target
    task, sid = await opened(db_session, packet)
    await db_session.commit()
    if variant == "before":
        monkeypatch.setattr(
            service.FormService,
            "context",
            original("backend/app/browser/service.py").FormService.context,
        )
        monkeypatch.setattr(
            chrome_profiles,
            "require_profile",
            original("backend/app/browser/chrome_profiles.py").require_profile,
        )
        legacy_lock = original("backend/app/agent/store.py").memory_row
        monkeypatch.setattr(store, "memory_row", legacy_lock)
        from backend.app.execution import store as execution_store

        monkeypatch.setattr(execution_store, "owner_lock", legacy_lock)
    counts = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        counts.append(statement.split()[0])
        time.sleep(0.02)

    engine = db_session.bind
    instrument_engine(engine)
    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    current = {"request_id": "fixture-" + variant, "stages": {}}
    token = trace.set(current)
    began = time.perf_counter()
    try:
        task, plan = await inspect_task(db_session, job, packet, task, sid)
        await db_session.commit()
    finally:
        trace.reset(token)
        event.remove(engine.sync_engine, "before_cursor_execute", observe)
    print(
        "BENCHMARK "
        + json.dumps(
            {
                "variant": variant,
                "seconds": round(time.perf_counter() - began, 4),
                "roundtrips": len(counts),
                "injected_roundtrip_seconds": 0.02,
                "stages": current["stages"],
            }
        )
    )
