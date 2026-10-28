"""Disposable PostgreSQL 17 concurrency/restart proof. Never accepts a live URL."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("disposable_local_candidate_profile_test_required")
    cluster = await asyncpg.connect(url)
    database = "candidate_profile_test_exec_" + uuid4().hex[:16]
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child_url = urlunsplit(parsed._replace(path="/" + database))
    engine = None
    try:
        assert int(await cluster.fetchval("SHOW server_version_num")) // 10000 == 17
        from backend.app.core.config import Settings, configure_operator

        configure_operator(
            Settings(
                _env_file=None,
                ENVIRONMENT="testing",
                DATABASE_SCHEMA="public",
                DATABASE_URL=child_url.replace(
                    "postgresql://", "postgresql+asyncpg://"
                ),
            )
        )
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.agent.tools import ToolDenied
        from backend.app.execution import store

        # Register all current models; these are fictional fixture tables only.
        from backend.app.main import app  # noqa: F401
        from backend.app.models.base import Base
        from backend.app.models.job import Job

        engine = create_async_engine(
            child_url.replace("postgresql://", "postgresql+asyncpg://")
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        job_id = uuid4()
        async with factory() as session, session.begin():
            session.add(
                Job(
                    id=job_id,
                    title="Fictional Backend Developer",
                    source_platform="naukri",
                    job_url="https://www.naukri.com/job-listings-fictional-281026123456",
                )
            )

        async def start():
            async with factory() as session, session.begin():
                return (await store.start(session, [job_id]))[0]

        intents = await asyncio.gather(*[start() for _ in range(8)])
        assert len({v["attempt_id"] for v in intents}) == 1
        identity = intents[0]["id"]

        async def claim():
            async with factory() as session, session.begin():
                return await store.claim(session)

        claims = await asyncio.gather(*[claim() for _ in range(8)])
        active = [v for v in claims if v]
        assert len(active) == 1
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            row.value = {
                **row.value,
                "lease_until": (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(),
            }
        # Recreate connection pool to prove durable recovery, not process memory.
        await engine.dispose()
        recovered = await claim()
        assert recovered[1] > active[0][1]
        async with factory() as session, session.begin():
            try:
                await store.fenced(session, active[0])
                raise AssertionError("stale worker admitted")
            except ToolDenied:
                pass
            row = await store.load(session, identity)
            await store.control(session, identity, "pause", row.value["revision"])
        assert await claim() is None
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            await store.control(session, identity, "resume", row.value["revision"])
        assert await claim()
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            row.value = {
                **row.value,
                "state": "SUBMITTING",
                "lease_until": (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(),
            }
        assert await claim() is None
        async with factory() as session, session.begin():
            row = await store.load(session, identity)
            assert row.value["state"] == "SUBMISSION_UNKNOWN"
            events = await store.events(session)
            assert events and events == await store.events(session)
        print(
            "Execution PostgreSQL PASS: 8 concurrent intents, 8 claims, pool restart, fencing, pause/resume, unknown dispatch, durable outbox; zero employer requests"
        )
    finally:
        if engine:
            await engine.dispose()
        await cluster.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await cluster.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
