"""Restricted PostgreSQL 17 + real Chrome + Telegram + localhost employer acceptance.

Creates and drops only a task-named disposable database. Never production DDL.
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url):
    import asyncpg

    p = urlsplit(url)
    if (
        p.hostname not in {"127.0.0.1", "localhost", "::1"}
        or p.path != "/candidate_profile_test"
        or p.query
        or p.fragment
    ):
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    cluster = await asyncpg.connect(url)
    if int(await cluster.fetchval("SHOW server_version_num")) // 10000 != 17:
        raise ValueError("PostgreSQL 17 required")
    suffix = uuid4().hex[:12]
    database, owner_role, runtime_role = (
        "candidate_profile_test_submit_" + suffix,
        "submit_owner_" + suffix,
        "submit_runtime_" + suffix,
    )
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child = urlunsplit(p._replace(path="/" + database))
    admin, engine, driver, fixture = None, None, None, None
    try:
        admin = await asyncpg.connect(child)
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await admin.execute(f'CREATE ROLE "{role}" NOLOGIN')
        sql = (ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text()
        await admin.execute(
            sql.replace("job_agent_owner", owner_role).replace(
                "job_agent_runtime", runtime_role
            )
        )
        from backend.app.core.config import Settings, configure_operator

        settings = Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_SCHEMA="public",
            DATABASE_URL=child.replace("postgresql://", "postgresql+asyncpg://"),
            COHERE_ENABLED=False,
            TELEGRAM_OWNER_USER_ID=111,
            TELEGRAM_OWNER_CHAT_ID=111,
        )
        configure_operator(settings)
        import pytest
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        import backend.app.db.session as db_module
        from backend.app.browser.submission import SubmissionService
        from backend.app.browser.submission_worker import SubmissionWorker
        from backend.app.browser.worker import BrowserWorker, ChromeDriver
        from backend.app.local_agent.models import AgentOperation, TelegramDelivery
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.tests.submission_acceptance import filled, submission_site
        from backend.tests.submission_fixtures import OWNER, approval

        engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=6,
            max_overflow=0,
            connect_args={"server_settings": {"role": runtime_role}},
            hide_parameters=True,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        db_module._engine, db_module._session_factory = engine, factory
        with tempfile.TemporaryDirectory(prefix="automated-apply-submit-pg-") as tmp:
            monkeypatch = pytest.MonkeyPatch()
            fixture = submission_site.__wrapped__(Path(tmp), monkeypatch)
            site = await anext(fixture)
            driver = ChromeDriver(
                (Path(tmp) / "automated-apply-automation").resolve(), headless=True
            )
            async with factory() as session:
                profile = await CandidateProfileRepository(
                    session
                ).create_primary_profile(
                    CandidateProfileCreate(
                        full_name="Alex Example",
                        email="alex@example.com",
                        verified_skills=["Python", "FastAPI"],
                        verified_experience_years=2,
                        preferences={"target_titles": ["Backend Engineer"]},
                    )
                )
                await session.commit()
                cfg, packet_id, worker, message, _, _ = await filled(
                    session, profile, site, driver, telegram=True
                )
                service = SubmissionService(session, cfg)
                _, s = await service.load(packet_id)
                await service.approve(packet_id, OWNER, approval(s))
                await session.commit()
                queued = await message(
                    "Submit the approved application for job 1", 91004
                )
                assert queued.state == "waiting_browser", queued.reply

            async def claim():
                async with factory() as session:
                    result = await SubmissionService(session, cfg).claim()
                    await session.commit()
                    return result

            claims = await asyncio.gather(claim(), claim())
            assert sum(c is not None for c in claims) == 1
            attempt = next(c for c in claims if c)
            async with factory() as locked:
                await SubmissionService(locked, cfg).load(packet_id)
                async with asyncio.timeout(3):
                    assert await claim() is None  # MVCC sees an active, locked lease.
            # Dispatch with the claimed fence, then lose completion exactly like a dead worker.
            response = await driver.call(
                "submit_application",
                document_id=attempt.document_id,
                document_digest=attempt.document_digest,
                idempotency_key=str(attempt.idempotency_key),
                expires_at=attempt.expires_at,
            )
            assert response["response"]["status"] == 200 and len(site[1]) == 1
            async with factory() as session:
                service = SubmissionService(session, cfg)
                row, current = await service.load(packet_id)
                current.lease_until = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
                service.save(row, current)
                await session.commit()
            await (
                engine.dispose()
            )  # Actual connection-pool restart; ledger survives it.
            assert await BrowserWorker(factory, cfg, driver).run_once() is None
            async with factory() as session:
                from backend.app.agent.tools import ToolDenied

                try:
                    await SubmissionService(session, cfg).fenced(
                        packet_id, attempt.fence
                    )
                    raise AssertionError("Expired worker fence accepted")
                except ToolDenied:
                    await session.rollback()
            result = await SubmissionWorker(factory, cfg, driver).reconcile(packet_id)
            assert result.state == "submitted" and result.evidence
            async with factory() as session:
                service = SubmissionService(session, cfg)
                await service.publish(result)
                await service.publish(result)
                await session.commit()
                count = await session.scalar(
                    select(func.count())
                    .select_from(AgentOperation)
                    .where(AgentOperation.command == "submission_receipt_verified")
                )
                assert count == 1
                notices = (await session.scalars(select(TelegramDelivery))).all()
                assert any("Submitted with evidence" in d.reply for d in notices)
                assert (await service.release(packet_id, OWNER)).state == "submitted"
                assert await service.claim() is None
            # Receipts/audit history remain insert-only under actual runtime privileges.
            for privilege in ("UPDATE", "DELETE"):
                assert not await admin.fetchval(
                    "SELECT has_table_privilege($1,'public.agent_operations',$2)",
                    runtime_role,
                    privilege,
                )
            assert len(site[1]) == 1 and site[3].exists()
            print(
                "Submission PostgreSQL PASS: real Chrome POST, durable employer receipt, Telegram executor, exact approval, concurrent claims, locked lease, fencing, lost completion, engine restart, read-only reconciliation, append-only audit, one POST"
            )
            await driver.close()
            driver = None
            await fixture.aclose()
            fixture = None
            monkeypatch.undo()
    finally:
        if driver:
            await driver.close()
        if fixture:
            await fixture.aclose()
        if engine:
            await engine.dispose()
        if admin:
            await admin.close()
        await cluster.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        for role in (runtime_role, owner_role):
            if await cluster.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await cluster.execute(f'DROP ROLE "{role}"')
        await cluster.close()


if __name__ == "__main__":
    import fcntl

    with open("/tmp/automated-apply-heavy-tests.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
