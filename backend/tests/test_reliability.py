"""Isolated regression evidence for idle contention, worker leases and outages."""

import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from backend.app.core.config import Settings
from backend.app.db.errors import database_failure_code


def lock_settings():
    return Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public",
                    DATABASE_URL="postgresql+asyncpg://fixture:fictional@127.0.0.1/candidate_profile_test")


@pytest.mark.parametrize("service", ["api", "execution", "telegram", "discovery", "resume"])
@pytest.mark.asyncio
async def test_actual_process_lease_blocks_duplicate_and_recovers_after_crash(tmp_path, service):
    from backend.app.local_agent.process_lock import WorkerAlreadyRunning, process_lock

    code = '''
import asyncio, sys
from backend.app.core.config import Settings
from backend.app.local_agent.process_lock import process_lock
async def main():
    config = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public",
        DATABASE_URL="postgresql+asyncpg://fixture:fictional@127.0.0.1/candidate_profile_test")
    async with process_lock(config, sys.argv[2], directory=sys.argv[1]):
        print("LOCKED", flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
'''
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), service],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), timeout=10)
        assert ready.strip() == "LOCKED"
        async with asyncio.timeout(1):
            with pytest.raises(WorkerAlreadyRunning, match=service + "_worker_already_running"):
                async with process_lock(lock_settings(), service, directory=tmp_path):
                    pytest.fail("Duplicate process admitted")
    finally:
        process.terminate()
        await asyncio.to_thread(process.wait, timeout=10)
        process.stdout.close()
        process.stderr.close()
    async with process_lock(lock_settings(), service, directory=tmp_path):
        assert len(list(tmp_path.glob("*.lock"))) == 2


@pytest.mark.asyncio
async def test_worker_lease_rejects_symlink(tmp_path):
    from backend.app.local_agent.process_lock import process_lock
    from backend.app.operations.configuration import target_identity

    target = tmp_path / "protected"
    target.write_text("unchanged")
    (tmp_path / ("execution-" + target_identity(lock_settings()) + ".lock")).symlink_to(target)
    with pytest.raises(OSError):
        async with process_lock(lock_settings(), "execution", directory=tmp_path):
            pytest.fail("Symlink accepted")
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("error,expected", [
    (PoolTimeout("private SQL"), "pool_timeout"),
    (TimeoutError("private endpoint"), "probe_timeout"),
    (DBAPIError("private SQL", {}, SimpleNamespace(sqlstate="53300")), "connection_limit"),
    (DBAPIError("private SQL", {}, SimpleNamespace(sqlstate="55P03")), "lock_timeout"),
    (DBAPIError("private SQL", {}, SimpleNamespace(sqlstate="08006")), "connection_failure"),
    (DBAPIError("private SQL", {}, SimpleNamespace(sqlstate="23514")), "schema_constraint_violation"),
    (DBAPIError("private SQL", {}, SimpleNamespace(sqlstate="P0001")), "schema_guard_rejected"),
    (RuntimeError("private password"), "storage_unavailable"),
])
def test_database_diagnostics_use_fixed_codes(error, expected):
    assert database_failure_code(error) == expected


@pytest.mark.asyncio
async def test_raw_asyncpg_limit_is_503_with_no_replay_marker(monkeypatch):
    from fastapi import HTTPException

    from backend.app.db import session as module

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        connection = AsyncMock()
        rollback = AsyncMock()

    session = Session()
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    dependency = module.get_db_session()
    await anext(dependency)
    with pytest.raises(HTTPException) as failure:
        await dependency.athrow(asyncpg.TooManyConnectionsError("private role"))
    assert failure.value.status_code == 503 and not failure.value.headers
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_readiness_shares_live_probe_and_survives_one_cancelled_caller(async_client, monkeypatch):
    import backend.app.main as main

    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def connectivity(*args):
        calls.append(1)
        entered.set()
        await release.wait()

    monkeypatch.setattr(main, "database_connectivity", connectivity)
    monkeypatch.setattr(main, "_readiness_task", None)
    tasks = [asyncio.create_task(async_client.get("/ready")) for _ in range(3)]
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.sleep(.01)
    tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[0]
    assert not main._readiness_task.cancelled()
    release.set()
    assert all(response.status_code == 200 for response in await asyncio.gather(*tasks[1:]))
    assert calls == [1]
    # Once that observation finishes, a new request must see a new DB result.
    assert (await async_client.get("/ready")).status_code == 200
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_probe_does_not_retain_idle_slot_and_shutdown_disposes_both_engines(monkeypatch):
    from backend.app.db import session as module
    from backend.app.db.safety import database_target

    config = lock_settings()
    created = []
    engine = SimpleNamespace(url=database_target(config), dispose=AsyncMock())
    normal = SimpleNamespace(url=database_target(config), dispose=AsyncMock())

    def create(url, **kwargs):
        created.append(kwargs)
        return engine

    monkeypatch.setattr(module, "get_settings", lambda: config)
    monkeypatch.setattr(module, "create_async_engine", create)
    monkeypatch.setattr(module, "_engine", normal)
    monkeypatch.setattr(module, "_session_factory", None)
    monkeypatch.setattr(module, "_readiness_engine", None)
    assert module.get_readiness_engine() is module.get_readiness_engine()
    assert len(created) == 1
    from sqlalchemy.pool import NullPool

    assert created[0]["poolclass"] is NullPool
    assert "pool_size" not in created[0] and "max_overflow" not in created[0]
    assert created[0]["connect_args"]["server_settings"]["application_name"] == "automated-apply:readiness"
    await module.close_db_engine()
    engine.dispose.assert_awaited_once()
    normal.dispose.assert_awaited_once()


def test_first_probe_cannot_switch_away_from_audited_startup_target(monkeypatch):
    from backend.app.db import session as module
    from backend.app.db.safety import DatabaseConfigurationError, database_target

    config = lock_settings()
    audited = database_target(config).set(database="different_fixture")
    monkeypatch.setattr(module, "get_settings", lambda: config)
    monkeypatch.setattr(module, "_engine", SimpleNamespace(url=audited))
    monkeypatch.setattr(module, "_readiness_engine", None)
    with pytest.raises(DatabaseConfigurationError, match="database_target_changed_restart_required"):
        module.get_readiness_engine()
    assert module._readiness_engine is None
