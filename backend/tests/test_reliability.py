"""Isolated regression evidence for idle contention, worker leases and outages."""

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.errors import database_failure_code
from backend.app.db.session import get_session_factory
from backend.app.execution import recurring, store


async def forbidden_lock(*args, **kwargs):
    pytest.fail("An idle observation must not acquire the owner's global lock")


@pytest.mark.asyncio
async def test_idle_scheduler_updates_heartbeat_without_owner_lock(db_session, monkeypatch):
    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    for state in ("STOPPED", "PAUSED", "RUNNING"):
        await recurring.put(db_session, recurring.KEY, {
            "state": state, "revision": 1, "policy": None,
            "next_check_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        await recurring.tick(db_session)
        await db_session.commit()
        await recurring.heartbeat(get_session_factory())
    assert (await db_session.get(OwnerPreference, recurring.HEALTH)).value["heartbeat_at"]


@pytest.mark.asyncio
async def test_idle_claim_watch_and_email_intake_do_not_take_owner_lock(db_session, monkeypatch):
    from backend.app.agent import store as campaigns
    from backend.app.execution import alert_email
    from backend.app.execution.worker import watch

    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    monkeypatch.setattr(campaigns, "memory_row", forbidden_lock)
    assert await store.claim(db_session) is None
    assert await campaigns.claim(db_session) is None
    assert await watch(db_session) == 0
    await db_session.commit()
    assert await alert_email.poll(get_session_factory()) is None


@pytest.mark.asyncio
async def test_empty_telegram_question_queue_does_not_lock_or_send(db_session, monkeypatch):
    from backend.app.execution.questions import deliver_one

    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    bot = SimpleNamespace(call=AsyncMock(side_effect=AssertionError("No send authorized")))
    config = Settings(_env_file=None, TELEGRAM_OWNER_USER_ID=42, TELEGRAM_OWNER_CHAT_ID=42)
    assert await deliver_one(get_session_factory(), config, bot) is False
    bot.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_status_without_maintenance_does_not_take_owner_lock(db_session, monkeypatch):
    from backend.app.browser.chrome_profiles import listing

    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    result = await listing(db_session, Settings(_env_file=None))
    assert result["commands"] == result["profiles"] == []


@pytest.mark.asyncio
async def test_profile_expiry_rechecks_a_command_after_acquiring_fence(db_session, monkeypatch):
    from backend.app.browser import chrome_profiles

    key = chrome_profiles.COMMAND + "fictional"
    value = {"id": "fictional", "version": 1, "state": "executing",
             "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    row = OwnerPreference(key=key, value=value)
    db_session.add(row)
    await db_session.commit()
    locks = []

    async def lock_then_cancel(session, *, lock):
        locks.append(lock)
        current = await session.get(OwnerPreference, key)
        current.value = {**current.value, "state": "cancelled", "version": 2}

    monkeypatch.setattr(store, "memory_row", lock_then_cancel)
    result = await chrome_profiles.listing(db_session, Settings(_env_file=None))
    assert locks == [True]
    assert result["commands"][0]["state"] == "cancelled"
    assert result["commands"][0]["version"] == 2


@pytest.mark.parametrize("state,expected", [("queued", "expired"), ("leased", "outcome_unknown"), ("executing", "outcome_unknown")])
@pytest.mark.asyncio
async def test_profile_expiry_retains_unknown_outcome(db_session, state, expected):
    from backend.app.browser import chrome_profiles

    db_session.add(OwnerPreference(key=chrome_profiles.COMMAND + "fixture", value={
        "version": 1, "state": state,
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }))
    result = await chrome_profiles.listing(db_session, Settings(_env_file=None))
    assert result["commands"][0]["state"] == expected


def lock_settings():
    return Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public",
                    DATABASE_URL="postgresql+asyncpg://fixture:fictional@127.0.0.1/candidate_profile_test")


@pytest.mark.parametrize("service", ["execution", "telegram"])
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
        assert len(list(tmp_path.glob("*.lock"))) == 1


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
    (RuntimeError("private password"), "storage_unavailable"),
])
def test_database_diagnostics_use_fixed_codes(error, expected):
    assert database_failure_code(error) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    DBAPIError("fictional unavailable", {}, Exception("fixture")),
    asyncpg.TooManyConnectionsError("fictional role limit"),
])
async def test_telegram_database_outage_does_not_exit_or_resend(monkeypatch, failure):
    from backend.app.execution import questions
    from backend.app.local_agent import telegram
    from backend.app.local_agent.models import TelegramState

    factory = get_session_factory()
    stop = asyncio.Event()
    attempts = []

    async def outage_then_recover(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise failure
        stop.set()

    monkeypatch.setattr(questions, "deliver_one", outage_then_recover)
    bot = SimpleNamespace(verify=AsyncMock(return_value={"id": 42}), call=AsyncMock(return_value=[]))
    config = Settings(_env_file=None, TELEGRAM_OWNER_USER_ID=42, TELEGRAM_OWNER_CHAT_ID=42)
    await asyncio.wait_for(telegram.run_worker(config, factory, api=bot, stop=stop), timeout=10)
    assert len(attempts) == 2
    assert all(call.args[0] == "getUpdates" for call in bot.call.call_args_list)
    async with factory() as session:
        assert (await session.get(TelegramState, "primary")).last_error is None


@pytest.mark.asyncio
async def test_raw_asyncpg_limit_is_503_with_no_replay_marker(monkeypatch):
    from fastapi import HTTPException

    from backend.app.db import session as module

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        rollback = AsyncMock()

    session = Session()
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    dependency = module.get_db_session()
    await anext(dependency)
    with pytest.raises(HTTPException) as failure:
        await dependency.athrow(asyncpg.TooManyConnectionsError("private role"))
    assert failure.value.status_code == 503 and not failure.value.headers
    session.rollback.assert_awaited_once()
