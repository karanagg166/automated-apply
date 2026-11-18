"""Disposable PostgreSQL 17 restricted-role vertical/recovery acceptance. Fictional data only."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url):
    import asyncpg
    parsed = urlsplit(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.path != "/candidate_profile_test" or parsed.query or parsed.fragment:
        raise ValueError("Only disposable localhost candidate_profile_test is permitted")
    cluster = await asyncpg.connect(url)
    if int(await cluster.fetchval("SHOW server_version_num")) // 10000 != 17:
        raise ValueError("PostgreSQL 17 required")
    suffix = uuid4().hex[:12]
    database = "candidate_profile_test_command_" + suffix
    owner_role, runtime_role = "command_owner_" + suffix, "command_runtime_" + suffix
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child = urlunsplit(parsed._replace(path="/" + database))
    admin, engine = None, None
    try:
        admin = await asyncpg.connect(child)
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
                await admin.execute(f'CREATE ROLE "{role}" NOLOGIN')
        # Existing production bootstrap, unchanged on disk; unique role names isolate concurrent suites.
        sql = (ROOT / "supabase/fresh_public/001_phase1_public.sql").read_text()
        sql = sql.replace("job_agent_owner", owner_role).replace("job_agent_runtime", runtime_role)
        await admin.execute(sql)
        from backend.app.core.config import Settings, configure_operator
        settings = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="public",
            DATABASE_URL=child.replace("postgresql://", "postgresql+asyncpg://"),
            TELEGRAM_OWNER_USER_ID=111, TELEGRAM_OWNER_CHAT_ID=111, DISCOVERY_TIMEOUT_SECONDS=5,
            COHERE_ENABLED=False, COHERE_OWNER_TEXT_AUTHORIZED=False, COHERE_CANDIDATE_DATA_AUTHORIZED=False)
        configure_operator(settings)
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.agent import store
        from backend.app.agent.contracts import Message
        from backend.app.agent.executor import CommandExecutor
        from backend.app.agent.tools import ToolDenied
        from backend.app.local_agent.contracts import Actor
        from backend.app.local_agent.models import (
            AgentOperation,
            TelegramDelivery,
            TelegramState,
        )
        from backend.app.local_agent.profile_confirmation import confirm_profile
        from backend.app.local_agent.telegram import process_update
        from backend.app.models.application_packet import ApplicationPacket
        from backend.app.models.job import Job
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.tests.phase5a_fakes import target
        engine = create_async_engine(settings.DATABASE_URL, pool_size=4, max_overflow=0,
            connect_args={"server_settings": {"role": runtime_role}}, hide_parameters=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner = Actor(channel="owner", identity="primary")
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name="Fictional Agent Owner", email="owner@example.org", verified_skills=["Python", "FastAPI"],
                verified_experience_years=2, preferences={"target_titles": ["Backend Engineer"]}))
            await session.commit()
            job, _ = await target(session, profile)
            job.location, job.employment_type = "India", "full_time"
            await confirm_profile(session, profile, profile.version)
            session.add(TelegramState(key="primary", next_update_id=0, bot_id="fictional"))
            await session.commit()
            job_id = job.id
        def update(n, text):
            return {"update_id": n, "message": {"from": {"id": 111}, "chat": {"id": 111, "type": "private"}, "text": text}}
        async with factory() as session:
            assert await process_update(session, settings, update(300, "Find backend jobs in India"), "fictional")
            await session.commit()
        # Atomic duplicate delivery/intake with independent actual PostgreSQL connections.
        async def duplicate():
            async with factory() as session:
                accepted = await process_update(session, settings, update(300, "Find backend jobs in India"), "fictional")
                await session.commit()
                return accepted
        assert await asyncio.gather(duplicate(), duplicate()) == [False, False]
        worker = CommandExecutor(factory, settings)
        search = await worker.run_once()
        assert search.state == "completed" and [r["job_id"] for r in search.ranked_jobs] == [str(job_id)], search.model_dump()
        async with factory() as session:
            # Two workers can never claim the same owner task.
            command = await store.intake(session, settings, owner, Message(text="Prepare applications for the first one"))
            await session.commit()
        async def claim():
            async with factory() as session:
                result = await store.claim(session)
                await session.commit()
                return result
        claims = await asyncio.gather(claim(), claim())
        assert sum(c is not None for c in claims) == 1
        crashed = next(c for c in claims if c is not None)
        await store.heartbeat(factory, crashed.id, crashed.fence)
        async with factory() as session:
            second = await store.intake(session, settings, owner, Message(text="Only show startups"))
            await session.commit()
        async with factory() as locked_session:
            await store.load(locked_session, crashed.id, lock=True)
            # SKIP LOCKED must not hide an active lease while its row is being heartbeated.
            async with asyncio.timeout(3):
                assert await claim() is None
        async with factory() as session:
            await store.cancel(session, settings, owner, second.id)
            await session.commit()
        async with factory() as session:
            row, campaign = await store.load(session, command.id, lock=True)
            campaign.lease_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            store.save(row, campaign)
            await session.commit()
        # A new executor instance recovers the expired lease and creates exactly one actual packet.
        restarted = CommandExecutor(factory, settings)
        prepared = await restarted.run_once()
        assert str(job_id) in prepared.applications, prepared.model_dump()
        assert prepared.applications[str(job_id)]["submitted"] is False
        assert any(h.get("reason") == "expired_lease_recovered" for h in prepared.history)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ApplicationPacket)) == 1
            try:
                await store.fenced(session, crashed.id, crashed.fence)
                raise AssertionError("stale worker accepted")
            except ToolDenied:
                pass
            await session.rollback()
            cancelled = await store.intake(session, settings, owner, Message(text="Only show startups"))
            await session.commit()
            await store.cancel(session, settings, owner, cancelled.id)
            await session.commit()
        assert await restarted.run_once() is None
        # Failed external delivery cannot replay accepted work or overwrite immutable tool receipts.
        async with factory() as session:
            delivery = await session.get(TelegramDelivery, 300)
            delivery.state = "sending"
            await session.commit()
        assert not await duplicate()
        assert await restarted.run_once() is None
        assert not await admin.fetchval("SELECT has_table_privilege($1,'public.agent_operations','UPDATE')", runtime_role)
        # Persisted packet, selections and execution outcomes survive a new engine/session factory.
        await engine.dispose()
        async with factory() as session:
            restored = (await store.load(session, prepared.id))[1]
            assert restored.applications == prepared.applications
            assert await session.scalar(select(func.count()).select_from(ApplicationPacket)) == 1
            assert await session.scalar(select(func.count()).select_from(Job)) == 1
            assert await session.scalar(select(func.count()).select_from(AgentOperation).where(AgentOperation.command.like("agent_tool:%"))) == 3
        import httpx

        from backend.app.models.discovery import DiscoveryRun
        from backend.app.services.job_sources.direct_api import ArbeitnowAdapter
        from backend.app.services.job_sources.factory import JobSourceFactory
        calls = []
        def response(request):
            calls.append(request.method)
            return httpx.Response(200, json={"data": [{"slug": "fictional-durable-source", "url": "https://fixture.example.org/jobs/durable",
                "company_name": "Fictional Durable Discovery", "title": "Python Backend Engineer", "description": "Fictional Python role",
                "location": "India", "remote": True, "tags": ["Python"], "created_at": 1792962000}]})
        original = JobSourceFactory.get_adapter
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
                JobSourceFactory.get_adapter = staticmethod(lambda source, **kwargs: ArbeitnowAdapter(client))
                async with factory() as session:
                    await store.intake(session, settings, owner, Message(text="Find backend jobs in India from Arbeitnow"))
                    await session.commit()
                live_format_fixture = await restarted.run_once()
                assert live_format_fixture.state == "completed", live_format_fixture.model_dump()
                discovery = next(r for r in live_format_fixture.results if r["tool"] == "discovery")
                assert discovery["counts"]["inserted"] == 1 and len(live_format_fixture.ranked_jobs) == 1
                async with factory() as session:
                    assert await session.scalar(select(func.count()).select_from(DiscoveryRun)) == 1
                    assert await session.scalar(select(func.count()).select_from(Job)) == 2
                assert await restarted.run_once() is None and calls == ["GET"]
        finally:
            JobSourceFactory.get_adapter = original
        # Browser queue shares existing restricted private tables: no new grants or DDL.
        from backend.app.agent.contracts import Approval, Filters, Plan
        from backend.app.browser import queue as browser_queue
        from backend.app.dashboard.models import OwnerPreference
        browser_settings = settings.model_copy(update={"BROWSER_FILL_ENABLED":True,"BROWSER_AUTOMATION_ENABLED":True})
        async with factory() as session:
            saved_job = await session.get(Job,job_id)
            destination = "https://jobs.lever.co/fictional-owner/fictional-job"
            saved_job.source_platform = "manual_browser"
            saved_job.job_url = destination
            saved_job.application_url = destination
            await session.commit()
            # Refresh the fixture's packet snapshot after changing the saved destination.
            from backend.app.services.applications.service import (
                ApplicationPacketService,
            )
            packet = await session.scalar(select(ApplicationPacket).where(ApplicationPacket.job_id == job_id))
            _,_,snapshot = await ApplicationPacketService(session).builder.context(job_id)
            packet.snapshot = snapshot.model_dump(mode="json")
            await session.commit()
            command = await store.intake(session,browser_settings,owner,Message(text="Fill the first application"))
            command.plan = Plan(intent="fill",filters=Filters(),selected_jobs=[job_id])
            command.approval = Approval(expected_revision=command.revision,nonce=command.approval_nonce,scope="fill",platforms=["employer_forms"],maximum_applications=1)
            row,_ = await store.load(session,command.id)
            store.save(row,command)
            first = await browser_queue.enqueue(
                session, browser_settings, command, saved_job, executor="isolated_browser"
            )
            await session.commit()
            duplicate_job = await browser_queue.enqueue(
                session, browser_settings, command, saved_job, executor="isolated_browser"
            )
            assert first["browser_job"] == duplicate_job["browser_job"]
            await session.commit()
        async def browser_claim():
            async with factory() as session:
                result = await browser_queue.claim(session)
                await session.commit()
                return result
        browser_claims = await asyncio.gather(browser_claim(),browser_claim())
        assert sum(result is not None for result in browser_claims) == 1
        browser_key,browser_job = next(result for result in browser_claims if result)
        async with factory() as locked:
            await locked.get(OwnerPreference,browser_key,with_for_update=True)
            async with asyncio.timeout(3):
                assert await browser_claim() is None
        async with factory() as session:
            from backend.app.browser.contracts import Inspection
            from backend.app.browser.service import FormService
            plan = await FormService(session,browser_settings).inspect(packet.id,Inspection(document_id=str(uuid4()),url=saved_job.application_url,fields=[{"field_id":"f0","kind":"text","label":"Full name"}]),"local_automation")
            await FormService(session,browser_settings).review(plan.id,["f0"])
            await FormService(session,browser_settings).consume(plan.id,"local_automation")
            await session.commit()
            assert await session.scalar(select(func.count()).select_from(AgentOperation).where(AgentOperation.command == "browser:fill_authorized")) == 1
            row = await session.get(OwnerPreference,browser_key)
            row.value = {**row.value,"lease_until":(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}
            await session.commit()
        assert await browser_claim() is None
        async with factory() as session:
            row = await session.get(OwnerPreference,browser_key)
            assert row.value["state"] == "manual_required"
            try:
                await browser_queue.fenced(session,browser_key,browser_job["fence"])
                raise AssertionError("Lost browser lease accepted")
            except ToolDenied:
                pass
        assert not await admin.fetchval("SELECT has_table_privilege($1,'public.agent_operations','UPDATE')",runtime_role)
        print("Command PostgreSQL PASS: real bootstrap, restricted role, Telegram duplicate delivery, matching, packet preparation, atomic claims, expired lease recovery, fencing, cancellation, engine restart, no submissions")
    finally:
        if engine:
            await engine.dispose()
        if admin:
            await admin.close()
        await cluster.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        for role in (runtime_role, owner_role):
            if await cluster.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
                await cluster.execute(f'DROP ROLE "{role}"')
        await cluster.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
