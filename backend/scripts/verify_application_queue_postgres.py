"""Concurrent queue checks on a fresh loopback-only fictional PostgreSQL DB."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def verify(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or parsed.path != "/candidate_profile_test" or parsed.port in {None, 5432, 54322}
            or parsed.query or parsed.username != "postgres" or parsed.password):
        raise ValueError("fresh_disposable_loopback_postgresql_required")
    from backend.app.core.config import Settings, configure_operator

    settings = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="job_agent",
                        DATABASE_URL=url.replace("postgresql://", "postgresql+asyncpg://", 1))
    configure_operator(settings)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.agent.tools import ToolDenied
    from backend.app.execution import application_queue as queue
    from backend.app.execution.queue_contracts import (
        PlatformQueuePolicy,
        QueueControl,
        QueuePolicy,
        QueuePolicyUpdate,
    )
    from backend.app.main import app  # noqa: F401 -- registers ORM metadata
    from backend.app.models.base import Base

    started = perf_counter()
    engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True, pool_size=2, max_overflow=0,
                                 connect_args={"server_settings": {"search_path": "job_agent,public"}})
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    results = []
    url = "https://www.naukri.com/job-listings-fictional-291026123456"
    try:
        async with engine.begin() as connection:
            assert not await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')")), "fresh_database_required"
            await connection.execute(text("CREATE SCHEMA job_agent"))
            await connection.run_sync(Base.metadata.create_all)
            version = await connection.scalar(text("SHOW server_version"))
        async with factory() as session, session.begin():
            policy = QueuePolicy(platforms={"naukri": PlatformQueuePolicy(enabled=True)})
            saved = await queue.configure(session, QueuePolicyUpdate(expected_revision=0, policy=policy))
            current = await queue.control(session, QueueControl(expected_revision=saved["revision"], action="start"))

        async def enqueue():
            async with factory() as session, session.begin():
                return await queue.enqueue(session, "naukri", url, "saved_verified_job")

        messages = await asyncio.gather(enqueue(), enqueue())
        assert messages[0]["id"] == messages[1]["id"]
        results.append("concurrent_publish_one_durable_identity")

        async def claim(worker):
            async with factory() as session, session.begin():
                return await queue.claim(session, "naukri", {"worker": worker})

        claims = await asyncio.gather(claim("one"), claim("two"))
        assert sum(c is not None for c in claims) == 1
        winner = next(c for c in claims if c)
        results.append("concurrent_claim_one_lease")

        async def pause():
            async with factory() as session, session.begin():
                try:
                    return await queue.control(session, QueueControl(action="pause", expected_revision=current["revision"]))
                except ToolDenied:
                    return None

        pauses = await asyncio.gather(pause(), pause())
        assert sum(p is not None for p in pauses) == 1
        paused = next(p for p in pauses if p)
        results.append("concurrent_policy_control_one_revision_winner")
        async with factory() as session, session.begin():
            try:
                await queue.admit(session, winner["id"], winner["revision"], winner["lease_token"], winner["binding"])
            except ToolDenied as exc:
                assert str(exc) == "queue_lease_lost"
            else:
                raise AssertionError("paused_claim_was_admitted")
            await queue.control(session, QueueControl(action="start", expected_revision=paused["revision"]))
        results.append("stop_fences_prior_committed_lease")
        fresh = await claim("restart")
        assert fresh["lease_token"] != winner["lease_token"] and fresh["operation"] == "inspect_job"
        results.append("new_connection_resume_requires_fresh_read")
        async with factory() as session, session.begin():
            row = await queue.load(session, fresh["id"])
            row.value = {**row.value, "operation": "apply", "status": "executing", "stage": "APPLYING",
                         "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
        assert await claim("after_crash") is None
        async with factory() as session:
            saved = (await queue.load(session, fresh["id"])).value
            assert saved["stage"] == "SUBMISSION_UNKNOWN" and not saved["lease_token"]
            listing = await queue.listing(session, stage="SUBMISSION_UNKNOWN")
            assert listing["total"] == 1 and "lease_token" not in listing["items"][0]
        results.append("expired_possible_submission_is_never_redelivered")
        batch_urls = [f"https://www.naukri.com/job-listings-fictional-{291026220000 + i}" for i in range(20)]
        async def publish_batch():
            async with factory() as session, session.begin():
                return await queue.enqueue_batch(session, batch_urls, "naukri_ui_search")
        counts = await asyncio.gather(publish_batch(), publish_batch())
        assert sum(counts) == 20 and sorted(counts) == [0, 20]
        results.append("concurrent_twenty_item_batches_commit_one_outbox_per_identity")
        async with factory() as session, session.begin():
            config = await queue.configuration(session)
            await queue.control(session, QueueControl(action="stop", expected_revision=config["revision"]))
        async with factory() as reader:
            rows = [row.value for row in await queue.items(reader)]
            assert sum(v["stage"] == "PAUSED" for v in rows) == 20
            assert sum(v["stage"] == "SUBMISSION_UNKNOWN" for v in rows) == 1
        results.append("bulk_stop_persists_all_read_fences_and_keeps_unknown_submission")
        from sqlalchemy.exc import DBAPIError

        from backend.app.execution import store
        from backend.app.execution.queue_preparation import prepare_one

        async with factory() as session, session.begin():
            config = await queue.configuration(session)
            await queue.control(session, QueueControl(action="start", expected_revision=config["revision"]))
        async with factory() as holder, holder.begin():
            await store.memory_row(holder, lock=True)
            # A native transaction owns the real PostgreSQL row lock. An idle
            # preparation tick must still finish; only browser reads are queued.
            async with factory() as idle, idle.begin():
                await idle.execute(text("SET LOCAL lock_timeout = '100ms'"))
                began = perf_counter()
                assert await prepare_one(idle, settings) is False
                idle_seconds = round(perf_counter() - began, 6)
            try:
                async with factory() as legacy, legacy.begin():
                    await legacy.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    # Reproduce the former idle path, without changing its
                    # policy, lock scope or the held native transaction.
                    await queue.claim(legacy, "naukri", {"worker": "legacy_idle"}, operations={"prepare"})
            except DBAPIError as exc:
                assert exc.orig.sqlstate == "55P03"
            else:
                raise AssertionError("legacy_idle_path_did_not_contend")
        results.append("idle_preparation_bypasses_held_owner_lock_legacy_path_55P03")
        print(json.dumps({"fixture_only": True, "database_version": version, "cases_passed": len(results),
                          "duration_seconds": round(perf_counter() - started, 3), "pool_limit": 2,
                          "idle_preparation_under_held_lock_seconds": idle_seconds,
                          "provider_requests": 0, "applications": 0, "results": results}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    asyncio.run(verify(parser.parse_args().url))
