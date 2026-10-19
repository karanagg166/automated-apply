"""Verify 001–009 and startup races in a uniquely created disposable localhost DB."""

import asyncio
import os
import sys
import uuid
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
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase6a_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ.update(
            DATABASE_URL=isolated.replace("postgresql://", "postgresql+asyncpg://", 1),
            DATABASE_SCHEMA="job_agent",
            ENVIRONMENT="testing",
            GMAIL_SENDING_ENABLED="false",
            MCP_REMOTE_ENABLED="false",
            SERPER_API_KEY="",
            APIFY_API_TOKEN="",
        )
        import httpx
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.models.company import Company
        from backend.app.models.startup import CompanySourceObservation
        from backend.app.schemas.discovery import DiscoveryError
        from backend.app.services.discovery_budget import DiscoveryBudget
        from backend.app.services.startup_discovery.connectivity import claim_access
        from backend.app.services.startup_discovery.evidence import ingest_company
        from backend.app.services.startup_discovery.schemas import (
            ShortlistInput,
            StartupRunRequest,
        )
        from backend.app.services.startup_discovery.service import (
            StartupDiscoveryService,
        )
        from backend.tests.startup_fakes import observed

        async def no_http(*args, **kwargs):
            raise AssertionError("Live HTTP forbidden in PostgreSQL verification")

        httpx.AsyncHTTPTransport.handle_async_request = no_http
        connection = await asyncpg.connect(isolated)
        for role in ("anon", "authenticated", "service_role"):
            if not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await connection.execute(
                    f'CREATE ROLE "{role}" NOLOGIN'
                    + (" BYPASSRLS" if role == "service_role" else "")
                )
        for path in sorted((ROOT / "supabase/migrations").glob("00[1-8]*.sql")):
            await connection.execute(path.read_text())
        await connection.execute(
            "CREATE TABLE public.phase6a_sentinel(value text); INSERT INTO public.phase6a_sentinel VALUES('preserve')"
        )
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        await connection.execute(
            "INSERT INTO job_agent.companies(name,domain,metadata) VALUES('Legacy Company','legacy.example','{\"human_review\":true}')"
        )
        legacy = await connection.fetchrow(
            "SELECT to_jsonb(c) AS value FROM job_agent.companies c WHERE domain='legacy.example'"
        )
        migration = (
            ROOT / "supabase/migrations/009_live_startup_intelligence.sql"
        ).read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        assert public_before == await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        assert legacy == await connection.fetchrow(
            "SELECT to_jsonb(c) AS value FROM job_agent.companies c WHERE domain='legacy.example'"
        )
        for table in (
            "company_source_observations",
            "startup_shortlist_entries",
            "provider_connection_checks",
            "provider_access_windows",
        ):
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='job_agent' AND c.relname=$1",
                table,
            )
            for role in ("anon", "authenticated"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await connection.fetchval(
                        "SELECT has_table_privilege($1,$2,$3)",
                        role,
                        "job_agent." + table,
                        privilege,
                    )
            assert await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'SELECT')",
                "job_agent." + table,
            )
        assert not await connection.fetchval(
            "SELECT has_table_privilege('service_role','job_agent.company_source_observations','UPDATE')"
        )
        engine = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_size=15,
            max_overflow=5,
            hide_parameters=True,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        item = observed()

        async def ingest_once():
            async with factory() as session:
                company = await ingest_company(session, item)
                await session.commit()
                return company.id

        ids = await asyncio.gather(*(ingest_once() for _ in range(8)))
        assert len(set(ids)) == 1
        company_id = ids[0]
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.company_source_observations"
            )
            == 1
        )
        async with factory() as session:
            company = await ingest_company(
                session, observed(name="Fictional Robotics Alias")
            )
            assert company.id == company_id
            other = await ingest_company(
                session,
                observed(domain="different.example", source_company_id="different"),
            )
            assert other.id != company_id
            await session.rollback()
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.company_source_observations"
            )
            == 1
        )
        # Single durable run claim, irrespective of concurrent request arrival.
        request = StartupRunRequest(
            idempotency_key="postgres-startup-001",
            permission_confirmed=True,
            companies=[item],
        )

        async def run_once():
            async with factory() as session:
                return await StartupDiscoveryService(session, factory).run(request)

        runs = await asyncio.gather(*(run_once() for _ in range(8)))
        assert len({r["id"] for r in runs}) == 1
        run_id = uuid.UUID(runs[0]["id"])
        assert (
            await connection.fetchval(
                "SELECT status FROM job_agent.discovery_runs WHERE id=$1", run_id
            )
            == "success"
        )

        async def shortlist_once():
            async with factory() as session:
                return await StartupDiscoveryService(session, factory).shortlist(
                    company_id, ShortlistInput(note="Human note", run_id=run_id)
                )

        entries = await asyncio.gather(*(shortlist_once() for _ in range(8)))
        assert sum(e["created"] for e in entries) == 1
        assert (
            await connection.fetchval(
                "SELECT note FROM job_agent.startup_shortlist_entries WHERE company_id=$1",
                company_id,
            )
            == "Human note"
        )

        async def reserve_once(index):
            try:
                await DiscoveryBudget(factory).reserve(
                    "phase6a", f"startup-reservation-{index}", 1, 3
                )
                return True
            except DiscoveryError:
                return False

        assert sum(await asyncio.gather(*(reserve_once(i) for i in range(8)))) == 3

        async def pace_once():
            try:
                await claim_access(factory, "remotive")
                return True
            except DiscoveryError:
                return False

        assert sum(await asyncio.gather(*(pace_once() for _ in range(8)))) == 1

        async def rejects(statement, *args):
            try:
                await connection.execute(statement, *args)
            except asyncpg.PostgresError:
                return
            raise AssertionError("Invalid mutation accepted: " + statement)

        await rejects(
            "UPDATE job_agent.company_source_observations SET attributes='{}' WHERE company_id=$1",
            company_id,
        )
        await rejects(
            "INSERT INTO job_agent.company_source_observations(company_id,source,identity_key,content_hash,source_url) VALUES($1,'fixture','missing','missing','https://fictional.example')",
            uuid.uuid4(),
        )
        await rejects(
            "INSERT INTO job_agent.provider_connection_checks(provider,state,is_live,schema_valid,finished_at) VALUES('fixture','live_verified',false,true,now())"
        )
        assert await connection.fetchval("SELECT count(*) FROM job_agent.jobs") == 0
        assert await connection.fetchval("SELECT count(*) FROM job_agent.contacts") == 0
        assert legacy == await connection.fetchrow(
            "SELECT to_jsonb(c) AS value FROM job_agent.companies c WHERE domain='legacy.example'"
        )
        assert public_before == await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(CompanySourceObservation)
                )
                == 1
            )
            assert await session.scalar(select(func.count()).select_from(Company)) == 2
        print(
            "Phase 6A PostgreSQL PASS: 001–009 (009 twice); legacy/public preservation; RLS/grants/FKs; append-only company evidence; 8-worker identity/run/shortlist/window/budget races; rollback and idempotency; zero fake jobs, messages or applications"
        )
    finally:
        if engine is not None:
            await engine.dispose()
        if connection is not None:
            await connection.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1",
            database,
        )
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
