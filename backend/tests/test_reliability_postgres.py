"""Real lock/connection failures on a guarded disposable localhost database."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.errors import database_failure_code
from backend.app.models.base import Base


@pytest_asyncio.fixture
async def postgres():
    url = os.environ.get("PROFILE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicitly selected disposable localhost PostgreSQL")
    target = urlsplit(url)
    if (target.hostname not in {"127.0.0.1", "localhost", "::1"}
            or target.path != "/candidate_profile_test" or target.query or target.fragment):
        pytest.fail("disposable_local_candidate_profile_test_required")
    admin = await asyncpg.connect(url)
    database = "reliability_test_" + uuid4().hex[:16]
    role = "reliability_role_" + uuid4().hex[:16]
    await admin.execute(f'CREATE DATABASE "{database}"')
    await admin.execute(f'CREATE ROLE "{role}" LOGIN CONNECTION LIMIT 2')
    child_url = urlunsplit(target._replace(path="/" + database))
    engine = create_async_engine(child_url.replace("postgresql://", "postgresql+asyncpg://", 1),
                                 pool_size=1, max_overflow=0, pool_pre_ping=True,
                                 connect_args={"server_settings": {"lock_timeout": "200ms"}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield admin, child_url, role, engine
    finally:
        await engine.dispose()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.execute(f'DROP ROLE "{role}"')
        await admin.close()


@pytest.mark.asyncio
async def test_profile_status_and_idle_claim_do_not_wait_for_owner_transaction(postgres):
    from backend.app.agent import store as campaigns
    from backend.app.browser import chrome_profiles
    from backend.app.execution import store

    _, url, _, engine = postgres
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session, session.begin():
        await store.memory_row(session, lock=True)
    blocker = await asyncpg.connect(url)
    transaction = blocker.transaction()
    await transaction.start()
    await blocker.fetch("SELECT key FROM owner_preferences WHERE key=$1 FOR UPDATE", campaigns.MEMORY_KEY)
    try:
        # Reproduce the previous status entry condition: unconditional owner lock.
        began = time.monotonic()
        async with factory() as session:
            with pytest.raises(Exception) as failure:
                await store.memory_row(session, lock=True)
            assert database_failure_code(failure.value) == "lock_timeout"
        before = time.monotonic() - began
        began = time.monotonic()
        for _ in range(10):
            async with factory() as session:
                status = await asyncio.wait_for(chrome_profiles.listing(session, Settings(_env_file=None)), 1)
                assert status["profiles"] == []
                assert await asyncio.wait_for(store.claim(session), 1) is None
        after = (time.monotonic() - began) / 10
        print(json.dumps({"fixture": "owner_lock_contention", "before": "55P03",
                          "before_seconds": round(before, 4), "after_cycles": 10,
                          "after_seconds_per_cycle": round(after, 4)}))
    finally:
        await transaction.rollback()
        await blocker.close()
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_live_status_maintenance_rechecks_after_waiting_for_owner_lock(postgres):
    from backend.app.agent import store as campaigns
    from backend.app.browser import chrome_profiles
    from backend.app.execution import store

    _, _, _, engine = postgres
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session, session.begin():
        await store.memory_row(session, lock=True)
        session.add(OwnerPreference(key=chrome_profiles.COMMAND + "fixture", value={
            "state": "executing", "version": 1,
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }))
    # Separate pool: a real concurrent cancellation wins before the listing fence.
    other = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    other_factory = async_sessionmaker(other, expire_on_commit=False)
    try:
        async with other_factory() as owner, owner.begin():
            await owner.execute(select(OwnerPreference).where(
                OwnerPreference.key == campaigns.MEMORY_KEY).with_for_update())
            task = asyncio.create_task(_status(factory))
            async with asyncio.timeout(1):
                while not await owner.scalar(text("""
                    SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                        WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid)))
                """)):
                    await asyncio.sleep(.005)
            row = await owner.get(OwnerPreference, chrome_profiles.COMMAND + "fixture")
            row.value = {**row.value, "state": "cancelled", "version": 2}
        result = await task
        assert result["commands"][0]["state"] == "cancelled"
        assert result["commands"][0]["version"] == 2
    finally:
        await other.dispose()


async def _status(factory):
    from backend.app.browser import chrome_profiles

    async with factory() as session, session.begin():
        return await chrome_profiles.listing(session, Settings(_env_file=None))


@asynccontextmanager
async def limited_connection(url, role):
    target = urlsplit(url)
    connection = await asyncpg.connect(host=target.hostname, port=target.port,
                                       user=role, database=target.path[1:])
    try:
        yield connection
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_actual_connection_limit_rejects_then_recovers_without_budget_increase(postgres):
    _, url, role, _ = postgres
    async with limited_connection(url, role), limited_connection(url, role):
        with pytest.raises(asyncpg.TooManyConnectionsError) as failure:
            async with limited_connection(url, role):
                pytest.fail("Connection limit was not enforced")
        assert database_failure_code(failure.value) == "connection_limit"
    async with limited_connection(url, role) as connection:
        assert await connection.fetchval("SELECT 1") == 1


@pytest.mark.asyncio
async def test_concurrent_claims_restart_stop_and_unknown_dispatch_remain_fenced(postgres):
    from backend.app.agent.tools import ToolDenied
    from backend.app.execution import store
    from backend.app.models.job import Job

    _, _, _, base_engine = postgres
    engine = create_async_engine(base_engine.url, pool_size=4, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session, session.begin():
            job = Job(title="Fictional reliability role", source_platform="naukri",
                      job_url="https://www.naukri.com/job-listings-fictional-281026123456")
            session.add(job)
            await session.flush()
            identity = (await store.start(session, [job.id]))[0]["id"]

        async def claim():
            async with factory() as session, session.begin():
                return await store.claim(session)

        claims = [result for result in await asyncio.gather(*(claim() for _ in range(8))) if result]
        assert len(claims) == 1
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            row.value = {**row.value, "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
        await engine.dispose()
        recovered = await claim()
        assert recovered[1] > claims[0][1]
        async with factory() as session, session.begin():
            with pytest.raises(ToolDenied):
                await store.fenced(session, claims[0])
            row = await store.load(session, identity)
            await store.control(session, identity, "pause", row.value["revision"])
        assert await claim() is None
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            await store.control(session, identity, "resume", row.value["revision"])
        assert await claim()
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            row.value = {**row.value, "state": "SUBMITTING",
                         "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
        assert await claim() is None
        async with factory() as session:
            row = await store.load(session, identity)
            assert row.value["state"] == "SUBMISSION_UNKNOWN"
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_readiness_detects_real_database_outage_and_recovers(postgres, async_client, monkeypatch):
    import backend.app.main as main

    admin, url, role, _ = postgres
    target = urlsplit(url)
    config_url = f"postgresql+asyncpg://{role}:fictional@{target.hostname}:{target.port}{target.path}"
    engine = create_async_engine(config_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    config = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public",
                      DATABASE_URL=config_url, DB_REQUIRE_TLS=False, DB_REMOTE_ONLY=False)
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    try:
        assert (await async_client.get("/ready")).status_code == 200
        await engine.dispose()
        await admin.execute(f'ALTER ROLE "{role}" NOLOGIN')
        assert (await async_client.get("/ready")).status_code == 503
        assert (await async_client.get("/health")).status_code == 200
        await admin.execute(f'ALTER ROLE "{role}" LOGIN')
        assert (await async_client.get("/ready")).status_code == 200
    finally:
        await admin.execute(f'ALTER ROLE "{role}" LOGIN')
        await engine.dispose()
    assert engine.pool.checkedout() == 0
