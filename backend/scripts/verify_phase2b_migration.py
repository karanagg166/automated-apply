"""Real PostgreSQL DDL/race verification, restricted to a unique disposable local DB."""

import asyncio
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit
import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
    ):
        raise ValueError("Only a local candidate_profile_test database is permitted")
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase2b_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ["DATABASE_URL"] = isolated.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        os.environ["DATABASE_SCHEMA"] = "job_agent"
        os.environ["ENVIRONMENT"] = "testing"
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from backend.app.models.job import Job
        from backend.app.services.job_ingestion import JobIngestionService
        from backend.app.services.discovery_budget import DiscoveryBudget
        from backend.app.services.job_discovery_service import JobDiscoveryService
        from backend.app.schemas.discovery import DiscoveryError, RunRequest
        from backend.tests.discovery_fakes import job

        connection = await asyncpg.connect(isolated)
        for name in (
            "001_initial_schema.sql",
            "002_candidate_profile.sql",
            "003_candidate_resources_and_answer_drafts.sql",
        ):
            await connection.execute((ROOT / "supabase/migrations" / name).read_text())
        await connection.execute(
            "CREATE TABLE public.phase2b_sentinel(value text); INSERT INTO public.phase2b_sentinel VALUES('preserve')"
        )
        company_id = await connection.fetchval(
            "INSERT INTO job_agent.companies(name,domain) VALUES('Legacy','legacy.example.com') RETURNING id"
        )
        legacy_id = await connection.fetchval(
            "INSERT INTO job_agent.jobs(title,job_url,source_platform,company_id,status,match_explanation) VALUES('Legacy Engineer','https://example.com/legacy/?utm_source=alert','manual',$1,'applied','Human application notes') RETURNING id",
            company_id,
        )
        profile_id = await connection.fetchval(
            "INSERT INTO job_agent.candidate_profiles(full_name,email,version) VALUES('Example Person','example@example.com',9) RETURNING id"
        )
        await connection.execute(
            "INSERT INTO job_agent.candidate_resources(candidate_profile_id,resource_type,label,url) VALUES($1,'resume','Existing','https://example.com/resume')",
            profile_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.application_answer_drafts(candidate_profile_id,candidate_profile_version,question,answer,question_category,writing_style) VALUES($1,9,'Name?','Example Person','short_text','professional')",
            profile_id,
        )
        snapshots = {
            table: await connection.fetchval(
                f"SELECT jsonb_agg(to_jsonb(t))::text FROM job_agent.{table} t"
            )
            for table in (
                "candidate_profiles",
                "candidate_resources",
                "application_answer_drafts",
                "companies",
            )
        }
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        migration = (ROOT / "supabase/migrations/004_job_discovery.sql").read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        for table, snapshot in snapshots.items():
            assert (
                await connection.fetchval(
                    f"SELECT jsonb_agg(to_jsonb(t))::text FROM job_agent.{table} t"
                )
                == snapshot
            )
        assert (
            await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            == public_before
        )
        assert (
            await connection.fetchval(
                "SELECT status FROM job_agent.jobs WHERE id=$1", legacy_id
            )
            == "applied"
        )
        for table in (
            "discovery_runs",
            "job_source_observations",
            "discovered_company_people",
            "discovery_monthly_budgets",
            "discovery_budget_reservations",
        ):
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass",
                f"job_agent.{table}",
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1",
                    table,
                )
                == 0
            )
        engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Simultaneous transactions see one canonical identity and one company, with all observations.
        async def ingest(index):
            item = job(
                source_name="naukri" if index % 2 else "wellfound",
                source_job_id=str(index),
                original_url=f"https://example.com/aggregated/{index}",
                application_url="https://boards.greenhouse.io/example/jobs/123",
            )
            async with factory() as session:
                result = await JobIngestionService(session).ingest_jobs([item])
                await session.commit()
                assert not result.errors, result
                return result

        results = await asyncio.gather(*(ingest(i) for i in range(12)))
        assert sum(r.inserted_count for r in results) == 1
        assert sum(r.updated_count for r in results) == 11
        assert await connection.fetchval("SELECT count(*) FROM job_agent.jobs") == 2
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.job_source_observations"
            )
            == 12
        )
        assert (
            await connection.fetchval("SELECT count(*) FROM job_agent.companies") == 2
        )
        # Canonicalized legacy observation preserves application status/notes and old URL.
        async with factory() as session:
            result = await JobIngestionService(session).ingest_jobs(
                [
                    job(
                        source_name="manual",
                        source_job_id="legacy",
                        original_url="https://example.com/legacy",
                        company_name="Legacy",
                        company_domain="legacy.example.com",
                    )
                ]
            )
            await session.commit()
            assert result.updated_count == 1
            legacy = await session.get(Job, legacy_id)
            assert (
                legacy.status == "applied"
                and legacy.match_explanation == "Human application notes"
            )
            assert legacy.job_url.endswith("?utm_source=alert")

        # Same supporting evidence creates one identity under concurrent ingestion too.
        async def content_writer(i):
            async with factory() as session:
                result = await JobIngestionService(session).ingest_jobs(
                    [
                        job(
                            source_name="remotive",
                            source_job_id="content" + str(i),
                            original_url=f"https://remotive.com/job/{i}",
                            title="Content Engineer",
                        )
                    ]
                )
                await session.commit()
                assert not result.errors, result
                return result

        content_results = await asyncio.gather(*(content_writer(i) for i in range(6)))
        assert sum(r.inserted_count for r in content_results) == 1
        # Rollback is real: no job, company or observation survives a failed outer transaction.
        count_before = await connection.fetchval("SELECT count(*) FROM job_agent.jobs")
        async with factory() as session:
            result = await JobIngestionService(session).ingest_jobs(
                [
                    job(
                        source_job_id="rollback",
                        original_url="https://example.net/rollback",
                        company_name="Rollback",
                        company_domain="rollback.example.net",
                    )
                ]
            )
            assert result.inserted_count == 1
            await session.rollback()
        assert (
            await connection.fetchval("SELECT count(*) FROM job_agent.jobs")
            == count_before
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.companies WHERE name='Rollback'"
            )
            == 0
        )
        try:
            await connection.execute(
                "INSERT INTO job_agent.job_source_observations(job_id,source,identity_key,original_url) VALUES($1,'bad','bad','https://example.com/bad')",
                uuid.uuid4(),
            )
        except asyncpg.ForeignKeyViolationError:
            pass
        else:
            raise AssertionError("Invalid observation FK accepted")
        # Exact money accounting across independent connections, no float overshoot.
        budget = DiscoveryBudget(factory)

        async def reserve(i):
            try:
                await budget.reserve("apify", str(i), 0.1, 0.3)
                return "ok"
            except DiscoveryError as exc:
                return str(exc.status)

        reservations = await asyncio.gather(*(reserve(i) for i in range(12)))
        assert (
            reservations.count("ok") == 3
            and reservations.count("budget_exhausted") == 9
        ), reservations
        assert (
            float(
                await connection.fetchval(
                    "SELECT reserved FROM job_agent.discovery_monthly_budgets"
                )
            )
            == 0.3
        )
        await budget.cooldown("apify")
        try:
            await budget.reserve("apify", "cooldown", 0.1, 1)
        except DiscoveryError as exc:
            assert exc.status == "rate_limited"
        else:
            raise AssertionError("Cooldown ignored")
        # Durable idempotency protects even concurrent requests and provider failures.
        request = RunRequest(
            source="manual",
            query={"limit": 1},
            idempotency_key="once",
            use_profile=False,
            manual_jobs=[
                job(
                    source_name="manual",
                    source_job_id="request",
                    original_url="https://example.com/idempotent",
                    title="Unique Engineer",
                ).model_dump(mode="json")
            ],
        )

        async def discover():
            async with factory() as session:
                return await JobDiscoveryService(session, factory).run(request)

        runs = await asyncio.gather(*(discover() for _ in range(6)))
        assert len({r["id"] for r in runs}) == 1
        assert (
            await connection.fetchval("SELECT count(*) FROM job_agent.discovery_runs")
            == 1
        )
        assert (
            await connection.fetchval("SELECT status FROM job_agent.discovery_runs")
            == "success"
        ), runs
        # Retry migration after data exists, with no rewrites or deletion.
        before_replay = {
            table: await connection.fetchval(
                f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM job_agent.{table} t"
            )
            for table in (
                "jobs",
                "job_source_observations",
                "discovery_runs",
                "discovery_monthly_budgets",
                "discovery_budget_reservations",
            )
        }
        await connection.execute(migration)
        for table, snapshot in before_replay.items():
            assert (
                await connection.fetchval(
                    f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM job_agent.{table} t"
                )
                == snapshot
            )
        assert (
            await connection.fetchval("SELECT value FROM public.phase2b_sentinel")
            == "preserve"
        )
        assert (
            await connection.fetchval(
                "SELECT version FROM job_agent.candidate_profiles"
            )
            == 9
        )
        print(
            "Phase 2B PostgreSQL PASS: additive/replay DDL, old jobs/profiles/resources/drafts/public preserved, RLS, FK, 12 concurrent ATS ingestions, 6 content ingestions, observation history, manual state, rollback, 12 budget reservations, cooldown, concurrent run idempotency"
        )
    finally:
        if engine:
            await engine.dispose()
        if connection:
            await connection.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
