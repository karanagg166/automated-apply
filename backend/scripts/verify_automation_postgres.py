"""PG17 transactions and restart recovery with fictional HTTP, never live sources."""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    cluster = await asyncpg.connect(url)
    if int(await cluster.fetchval("SHOW server_version_num")) // 10000 != 17:
        raise ValueError("Phase 10 verification requires PostgreSQL 17")
    database = "candidate_profile_test_auto_" + uuid.uuid4().hex[:20]
    await cluster.execute(f'CREATE DATABASE "{database}"')
    child_url = urlunsplit(parsed._replace(path="/" + database))
    admin, engine = None, None
    try:
        admin = await asyncpg.connect(child_url)
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await admin.execute(f'CREATE ROLE "{role}" NOLOGIN')
        paths = sorted((ROOT / "supabase/migrations").glob("*.sql"))
        for path in paths[:11]:
            await admin.execute(path.read_text())
        await admin.execute(
            "INSERT INTO job_agent.companies(name) VALUES ('Fictional preservation probe')"
        )
        await admin.execute(paths[11].read_text())
        assert (
            await admin.fetchval("SELECT name FROM job_agent.companies")
            == "Fictional preservation probe"
        )
        for table in (
            "automation_schedule",
            "automation_executions",
            "automation_matches",
        ):
            assert await admin.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass",
                "job_agent." + table,
            )
            for role in ("anon", "authenticated"):
                assert not await admin.fetchval(
                    "SELECT has_table_privilege($1,$2,'SELECT')",
                    role,
                    "job_agent." + table,
                )
        import httpx
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.core.config import Settings, configure_operator

        settings = Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_URL=child_url.replace("postgresql://", "postgresql+asyncpg://"),
            AUTOMATION_EXECUTION_ENABLED=True,
            DISCOVERY_TIMEOUT_SECONDS=5,
        )
        configure_operator(settings)
        from backend.app.automation.models import AutomationExecution
        from backend.app.automation.schemas import (
            ManualRun,
            ScheduleConfiguration,
            ScheduleUpdate,
        )
        from backend.app.automation.store import (
            configuration,
            current_matches,
            manual_run,
            schedule,
            status,
            update_schedule,
        )
        from backend.app.automation.worker import DiscoveryWorker, LostLease
        from backend.app.dashboard.models import Notification, OwnerPreference
        from backend.app.dashboard.notifications import synchronize
        from backend.app.models.job import Job
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.schemas.discovery import DiscoveryResult, DiscoveryStatus
        from backend.app.services.candidate_profile_service import (
            CandidateProfileService,
        )
        from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
        from backend.app.services.job_sources.direct_api import (
            ArbeitnowAdapter,
            RemotiveAdapter,
        )
        from backend.app.services.startup_discovery.connectivity import claim_access

        engine = create_async_engine(
            settings.DATABASE_URL, hide_parameters=True, pool_size=4, max_overflow=0
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        clock = [datetime(2030, 1, 1, 12, tzinfo=timezone.utc)]
        calls, matches = [], []
        mode = ["success"]

        def transport(request):
            calls.append(str(request.url.host))
            assert request.method == "GET"
            if mode[0] == "timeout":
                raise httpx.ReadTimeout("fictional secret must stay redacted")
            if mode[0] == "rate_limit":
                return httpx.Response(429, headers={"Retry-After": "30000"})
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "slug": "fictional-python-job",
                            "url": "https://example.org/jobs/fictional",
                            "company_name": "Fictional Test Company",
                            "title": "Python Engineer",
                            "description": "Fictional listing: Python services",
                            "remote": True,
                            "location": "Worldwide",
                            "tags": ["Python"],
                            "created_at": 1700000000,
                        }
                    ],
                    "jobs": [],
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(transport))

        def adapter(source):
            assert source in {"arbeitnow", "remotive"}, (
                "Paid/unapproved source reached dispatch"
            )
            return (
                ArbeitnowAdapter(http)
                if source == "arbeitnow"
                else RemotiveAdapter(http)
            )

        original_match = JobDiscoveryMatcher.match

        def count_match(self, *args):
            matches.append(True)
            return original_match(self, *args)

        JobDiscoveryMatcher.match = count_match
        worker = DiscoveryWorker(
            factory, settings, clock=lambda: clock[0], adapter_factory=adapter
        )
        async with factory() as session, session.begin():
            session.add(
                OwnerPreference(
                    key="notifications",
                    value={
                        "quiet_start": 0,
                        "quiet_end": 0,
                        "minimum_job_score": 0,
                        "daily_digest": False,
                    },
                )
            )
            profile = await CandidateProfileService(session).create_profile(
                CandidateProfileCreate(
                    full_name="Alex Fictional",
                    email="alex@example.org",
                    verified_skills=["Python"],
                    verified_experience_years=2,
                    preferences={
                        "target_titles": ["Python Engineer"],
                        "remote_preference": "remote",
                    },
                )
            )

        async def configure(sources, approve=True, enabled=True):
            async with factory() as session, session.begin():
                row = await schedule(session)
                config = ScheduleConfiguration(
                    enabled=enabled,
                    sources=sources,
                    approved_profile_id=profile.id if approve else None,
                    approved_profile_version=profile.version if approve else None,
                )
                await update_schedule(
                    session,
                    ScheduleUpdate(expected_version=row.version, configuration=config),
                    settings,
                )
                row.next_run_at = clock[0] + timedelta(days=1) if enabled else None

        async def queue(key):
            async with factory() as session, session.begin():
                row = await schedule(session)
                await manual_run(
                    session,
                    ManualRun(expected_version=row.version, idempotency_key=key),
                    settings,
                )

        async def task(identity):
            async with factory() as session:
                return await session.get(AutomationExecution, identity[0])

        # Disabled startup and duplicate tick startup perform zero provider work.
        assert await worker.claim() is None
        assert not calls
        await configure(["arbeitnow"])
        await asyncio.gather(*(queue("same_manual_key") for _ in range(4)))
        await queue("different_key_coalesces")
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(AutomationExecution)
                )
                == 1
            )
        claims = await asyncio.gather(*(worker.claim() for _ in range(6)))
        assert len([c for c in claims if c]) == 1
        first = next(c for c in claims if c)
        # Crash before dispatch: backoff, new fence, stale worker denied.
        clock[0] += timedelta(seconds=241)
        assert await worker.claim() is None
        clock[0] += timedelta(seconds=31)
        recovered = await worker.claim()
        assert recovered[0] == first[0] and recovered[1] > first[1]
        try:
            await worker.dispatch(first)
        except LostLease:
            pass
        else:
            raise AssertionError("Stale claimant dispatched a request")
        await worker.execute(recovered)
        saved = await task(recovered)
        assert saved.state == "completed", saved.diagnostic
        assert (
            saved.outcome["counts"]["inserted"] == 1
            and saved.outcome["observation_ids"]
        )
        assert saved.outcome["evidence_mode"] == "mocked" and len(matches) == 1
        assert (
            saved.outcome["rankings"][0]["evidence"]["company"]["size"][
                "employee_count"
            ]
            is None
        )
        assert len(calls) == 1
        await queue("same_manual_key")
        assert await worker.claim() is None
        # Repeated manual key is durable even after completion; next key respects shared quota.
        await queue("second_run")
        assert await worker.claim() is None
        clock[0] += timedelta(seconds=61)
        second = await worker.claim()
        await worker.execute(second)
        assert (await task(second)).outcome["counts"]["duplicate"] == 1
        assert len(matches) == 1, "Unchanged evidence was unnecessarily rescored"
        # New attributable company-size evidence invalidates the existing cache;
        # the evidence remains company headcount, never invented team headcount.
        company_id = await admin.fetchval(
            "SELECT company_id FROM job_agent.jobs LIMIT 1"
        )
        await admin.execute(
            "INSERT INTO job_agent.company_source_observations(company_id,source,identity_key,content_hash,source_url,attributes,verification_status) VALUES ($1,'manual','fictional-size','fictional-content','https://example.org/fictional-company','{\"employee_count\":12,\"team_size_band\":\"11-50\"}','human_confirmed')",
            company_id,
        )
        clock[0] += timedelta(seconds=61)
        await queue("new_company_evidence")
        updated = await worker.claim()
        await worker.execute(updated)
        assert len(matches) == 2
        assert (await task(updated)).outcome["rankings"][0]["evidence"]["company"][
            "size"
        ]["employee_count"] == 12
        async with factory() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(Job)) == 1
            await synchronize(session, automation=True)
        async with factory() as session, session.begin():
            before = await session.scalar(
                select(func.count()).select_from(Notification)
            )
            assert (await synchronize(session, automation=True))["created"] == 0
            assert (
                await session.scalar(select(func.count()).select_from(Notification))
                == before
            )

        # Idle notification scans share one durable five-minute throttle.
        await worker.tick()
        async with factory() as session:
            scan = await session.get(OwnerPreference, "automation_notification_scan")
            first_scan = scan.value["next_at"]
        await worker.tick()
        async with factory() as session:
            scan = await session.get(OwnerPreference, "automation_notification_scan")
            assert scan.value["next_at"] == first_scan

        # Restart reconstructs all execution/profile state from PostgreSQL.
        await engine.dispose()
        worker = DiscoveryWorker(
            factory, settings, clock=lambda: clock[0], adapter_factory=adapter
        )
        async with factory() as session:
            assert (await status(session, settings))["matching"] == "approved"
            assert (
                len(
                    await current_matches(
                        session, configuration(await schedule(session))
                    )
                )
                == 1
            )
        # Crash after dispatch: no provider replay; late ingestion must roll back.
        clock[0] += timedelta(seconds=61)
        await queue("crashed_after_dispatch")
        dispatched = await worker.claim()
        await worker.dispatch(dispatched)
        calls_before = len(calls)
        clock[0] += timedelta(seconds=241)
        assert await worker.claim() is None
        assert (await task(dispatched)).diagnostic == "provider_outcome_unknown"
        try:
            await worker.complete(
                dispatched,
                DiscoveryResult(source="arbeitnow", status=DiscoveryStatus.SUCCESS),
            )
        except LostLease:
            pass
        else:
            raise AssertionError("Expired worker committed results")
        assert len(calls) == calls_before

        # Two-process bound, different sources; third claimant gets no capacity.
        await configure(["arbeitnow", "remotive"])
        await queue("bounded")
        claims = await asyncio.gather(worker.claim(), worker.claim(), worker.claim())
        assert len([c for c in claims if c]) == 2
        mode[0] = "rate_limit"
        await asyncio.gather(*(worker.execute(c) for c in claims if c))
        for c in claims:
            if c:
                record = await task(c)
                assert record.state == "blocked" and record.diagnostic == "rate_limited"
                assert record.outcome["counts"]["accepted"] == 0
                assert datetime.fromisoformat(
                    record.outcome["next_allowed_at"]
                ) >= clock[0] + timedelta(seconds=30000)
        # Quota from the worker also blocks existing manual discovery diagnostics.
        try:
            await claim_access(factory, "remotive", clock=lambda: clock[0])
        except ValueError:
            pass
        else:
            raise AssertionError("Shared source pacing bypassed")

        # Timeouts are redacted and never cause immediate provider replay.
        clock[0] += timedelta(seconds=30001)
        await configure(["arbeitnow"], approve=False)
        await queue("timeout")
        mode[0] = "timeout"
        timed = await worker.claim()
        await worker.execute(timed)
        record = await task(timed)
        assert record.state == "failed" and "secret" not in str(record.outcome)
        assert await worker.claim() is None
        # Missing approved profile permits discovery, produces no verified match.
        clock[0] += timedelta(seconds=301)
        mode[0] = "success"
        await queue("unapproved_profile")
        unapproved = await worker.claim()
        await worker.execute(unapproved)
        assert (await task(unapproved)).outcome[
            "matching"
        ] == "awaiting_profile_approval"
        assert (await task(unapproved)).outcome["rankings"] == []
        assert len(matches) == 2

        # Profile mutation makes cached personalized results unavailable.
        await configure(["arbeitnow"])
        await admin.execute(
            'UPDATE job_agent.candidate_profiles SET verified_skills=\'["Python","SQL"]\''
        )
        async with factory() as session:
            assert (await status(session, settings))[
                "matching"
            ] == "awaiting_profile_approval"
            assert (
                await current_matches(session, configuration(await schedule(session)))
                == []
            )

        # Owner disable invalidates pending and in-flight work before ingestion.
        clock[0] += timedelta(seconds=61)
        await configure(["arbeitnow"], approve=False)
        await queue("disable_during_provider")
        inflight = await worker.claim()
        await worker.dispatch(inflight)
        await configure(["arbeitnow"], approve=False, enabled=False)
        await worker.complete(
            inflight,
            DiscoveryResult(source="arbeitnow", status=DiscoveryStatus.SUCCESS),
        )
        assert (await task(inflight)).diagnostic == "configuration_changed"
        assert await worker.claim() is None

        # Rollback leaves no queued task; database constraints enforce idempotency.
        async with factory() as session:
            row = await schedule(session)
            row.enabled = True
            await session.flush()
            from backend.app.automation.store import enqueue

            await enqueue(session, row, "rolled_back", "manual", clock[0])
            await session.rollback()
        assert not await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM job_agent.automation_executions WHERE request_key='rolled_back')"
        )
        try:
            await admin.execute(
                "INSERT INTO job_agent.automation_executions SELECT * FROM job_agent.automation_executions LIMIT 1"
            )
        except asyncpg.UniqueViolationError:
            pass
        else:
            raise AssertionError(
                "Unique constraints did not reject duplicate execution"
            )

        # No paid source can pass configuration. Unknown paid outcomes stay in the
        # existing reservation ledger; this worker never invokes or reconciles it.
        from pydantic import ValidationError

        try:
            ScheduleConfiguration(enabled=True, sources=["wellfound"])
        except ValidationError:
            pass
        else:
            raise AssertionError("Paid automation was accepted")
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM job_agent.outreach_send_attempts"
            )
            == 0
        )
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM job_agent.application_submission_evidence"
            )
            == 0
        )
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM job_agent.discovery_budget_reservations"
            )
            == 0
        )

        # Due scheduler startup is distinct from manual enqueue: concurrent
        # schedulers coalesce a long outage into one batch, then persist next due.
        clock[0] += timedelta(seconds=301)
        await configure(["arbeitnow"], approve=False)
        async with factory() as session, session.begin():
            row = await schedule(session, lock=True)
            row.next_run_at = clock[0] - timedelta(days=30)
        due_claims = await asyncio.gather(*(worker.claim() for _ in range(5)))
        due = [c for c in due_claims if c]
        assert len(due) == 1 and (await task(due[0])).trigger_type == "scheduled"
        await worker.execute(due[0])
        assert (await task(due[0])).state == "completed"
        async with factory() as session:
            row = await schedule(session)
            assert row.next_run_at == clock[0] + timedelta(seconds=21600)
            assert row.last_run_at == clock[0]
        assert await worker.claim() is None

        # Expiry after ingestion starts rolls back jobs, observations, audit and
        # cache as one transaction, rather than merely blocking the task update.
        clock[0] += timedelta(seconds=61)
        await queue("expire_during_ingestion")
        expiring = await worker.claim()
        await worker.dispatch(expiring)
        from backend.app.schemas.normalized_job import NormalizedJob
        from backend.app.services.job_ingestion import JobIngestionService

        original_ingest = JobIngestionService.ingest_jobs

        async def delayed_ingest(self, jobs, **kwargs):
            output = await original_ingest(self, jobs, **kwargs)
            clock[0] += timedelta(seconds=241)
            return output

        JobIngestionService.ingest_jobs = delayed_ingest
        try:
            await worker.complete(
                expiring,
                DiscoveryResult(
                    source="arbeitnow",
                    status=DiscoveryStatus.SUCCESS,
                    jobs=[
                        NormalizedJob(
                            source_name="arbeitnow",
                            title="Fictional rollback-only role",
                            company_name="Fictional Rollback Company",
                            original_url="https://example.org/jobs/rollback-only",
                        )
                    ],
                ),
            )
        except LostLease:
            pass
        else:
            raise AssertionError("Expired ingestion transaction committed")
        finally:
            JobIngestionService.ingest_jobs = original_ingest
        assert not await admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM job_agent.jobs WHERE job_url='https://example.org/jobs/rollback-only')"
        )
        assert (await task(expiring)).state == "running"
        assert await worker.claim() is None
        assert (await task(expiring)).state == "blocked"

        # Existing unknown paid reservations retain the full cost cap across
        # restarts/ticks. The scheduler never releases or replays them.
        from backend.app.services.discovery_budget import DiscoveryBudget

        budget = DiscoveryBudget(factory)
        await budget.reserve("apify", "fictional_unknown_paid", 0.1, 1)
        await budget.finish("fictional_unknown_paid", "unknown")
        await configure(["arbeitnow"], approve=False, enabled=False)
        assert await worker.claim() is None
        assert (
            await admin.fetchval(
                "SELECT state FROM job_agent.discovery_budget_reservations WHERE id='fictional_unknown_paid'"
            )
            == "unknown"
        )
        assert (
            float(
                await admin.fetchval(
                    "SELECT reserved FROM job_agent.discovery_budget_reservations WHERE id='fictional_unknown_paid'"
                )
            )
            == 0.1
        )
        await http.aclose()
        print(
            "Automation PostgreSQL PASS: PG17 migration/RLS; duplicate startup; six-worker claim race; manual coalescing/idempotency; pre-dispatch recovery/fencing; post-dispatch unknown blocked; stale completion rollback; cross-process concurrency bound; shared quotas/429 Retry-After; redacted timeout; job/observation deduplication; approved profile match cache; notification deduplication; restart; disable fencing; rollback; no paid/application/email execution"
        )
    finally:
        if engine:
            await engine.dispose()
        if admin:
            await admin.close()
        await cluster.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1",
            database,
        )
        await cluster.execute(f'DROP DATABASE "{database}"')
        await cluster.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
