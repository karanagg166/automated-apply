"""Verify 001-005 in a unique disposable localhost database. Never production."""

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
    ):
        raise ValueError("Only local candidate_profile_test is permitted")
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase3_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ["DATABASE_URL"] = isolated.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        os.environ["DATABASE_SCHEMA"] = "job_agent"
        os.environ["ENVIRONMENT"] = "testing"
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.models.contact import Contact
        from backend.app.schemas.discovery import DiscoveryError
        from backend.app.services.contact_enrichment.contact_identity import (
            ContactIdentityResolver,
        )
        from backend.app.services.contact_enrichment.schemas import EnrichInput
        from backend.app.services.contact_enrichment.service import (
            ContactEnrichmentService,
        )
        from backend.app.services.discovery_budget import DiscoveryBudget
        from backend.tests.contact_enrichment_fakes import (
            URL,
            FakeApollo,
            FakeSignal,
            person,
            settings,
        )

        connection = await asyncpg.connect(isolated)
        for path in sorted((ROOT / "supabase/migrations").glob("00[1-4]*.sql")):
            await connection.execute(path.read_text())
        company_id = await connection.fetchval(
            "INSERT INTO job_agent.companies(name,domain) VALUES('Fictional Startup','fictional.example.com') RETURNING id"
        )
        legacy_id = await connection.fetchval(
            "INSERT INTO job_agent.contacts(company_id,full_name,role_title,linkedin_url,email,email_status,confidence_score) VALUES($1,'Alex Fictional','CTO',$2,'alex@fictional.example.com','verified',87) RETURNING id",
            company_id,
            URL,
        )
        job_id = await connection.fetchval(
            "INSERT INTO job_agent.jobs(company_id,title,job_url,source_platform) VALUES($1,'Engineer','https://fictional.example.com/jobs/1','manual') RETURNING id",
            company_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.outreach_logs(job_id,contact_id,subject,body,approval_status) VALUES($1,$2,'Legacy','Retain history','pending_approval')",
            job_id,
            legacy_id,
        )
        profile_id = await connection.fetchval(
            "INSERT INTO job_agent.candidate_profiles(full_name,email) VALUES('Example','example@example.com') RETURNING id"
        )
        await connection.execute(
            "INSERT INTO job_agent.candidate_resources(candidate_profile_id,resource_type,label,url) VALUES($1,'resume','Legacy','https://example.com/resume')",
            profile_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.application_answer_drafts(candidate_profile_id,candidate_profile_version,question,answer,question_category,writing_style) VALUES($1,1,'Name?','Example','short_text','professional')",
            profile_id,
        )
        await connection.execute(
            "CREATE TABLE public.phase3_sentinel(value text); INSERT INTO public.phase3_sentinel VALUES('retain')"
        )
        tables = [
            "companies",
            "jobs",
            "candidate_profiles",
            "candidate_resources",
            "candidate_evidence",
            "application_answer_drafts",
            "outreach_logs",
            "discovered_company_people",
        ]
        snapshots = {
            t: await connection.fetchval(
                f"SELECT jsonb_agg(to_jsonb(t))::text FROM job_agent.{t} t"
            )
            for t in tables
        }
        legacy = dict(
            await connection.fetchrow(
                "SELECT * FROM job_agent.contacts WHERE id=$1", legacy_id
            )
        )
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        migration = (
            ROOT / "supabase/migrations/005_contact_enrichment.sql"
        ).read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        for table, snapshot in snapshots.items():
            assert (
                await connection.fetchval(
                    f"SELECT jsonb_agg(to_jsonb(t))::text FROM job_agent.{table} t"
                )
                == snapshot
            )
        after = dict(
            await connection.fetchrow(
                "SELECT * FROM job_agent.contacts WHERE id=$1", legacy_id
            )
        )
        assert all(after[key] == value for key, value in legacy.items())
        assert not after["do_not_contact"] and after["last_checked_at"] is None
        assert (
            await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            == public_before
        )
        assert (
            await connection.fetchval("SELECT value FROM public.phase3_sentinel")
            == "retain"
        )
        for table in [
            "contacts",
            "contact_enrichment_runs",
            "contact_evidence",
            "contact_identities",
            "contact_provider_lookups",
        ]:
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass",
                "job_agent." + table,
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1",
                    table,
                )
                == 0
            )
        # Real foreign-key and uniqueness enforcement.
        try:
            await connection.execute(
                "INSERT INTO job_agent.contact_identities(company_id,contact_id,namespace,identity_key) VALUES($1,$2,'invalid','fk')",
                company_id,
                uuid.uuid4(),
            )
            raise AssertionError("Missing foreign key")
        except asyncpg.ForeignKeyViolationError:
            pass
        engine = create_async_engine(
            os.environ["DATABASE_URL"],
            connect_args={"server_settings": {"search_path": "job_agent,public"}},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def reconcile(i):
            async with factory() as session:
                result = await ContactIdentityResolver(session).reconcile(
                    company_id,
                    person(
                        source="apollo" if i % 2 else "signalhire",
                        provider_person_id="same-id",
                    ),
                )
                await session.commit()
                return result[0].id

        identities = await asyncio.gather(*(reconcile(i) for i in range(12)))
        assert set(identities) == {legacy_id}
        assert await connection.fetchval("SELECT count(*) FROM job_agent.contacts") == 1
        assert (
            await connection.fetchval("SELECT count(*) FROM job_agent.contact_evidence")
            == 12
        )
        assert (
            await connection.fetchval(
                "SELECT email_status FROM job_agent.contacts WHERE id=$1", legacy_id
            )
            == "verified"
        )
        try:
            await connection.execute(
                "INSERT INTO job_agent.contact_identities(company_id,contact_id,namespace,identity_key) VALUES($1,$2,'linkedin',$3)",
                company_id,
                legacy_id,
                URL,
            )
            raise AssertionError("Missing identity uniqueness")
        except asyncpg.UniqueViolationError:
            pass
        before_count = await connection.fetchval(
            "SELECT count(*) FROM job_agent.contacts"
        )
        async with factory() as session:
            await ContactIdentityResolver(session).reconcile(
                company_id,
                person(
                    full_name="Rollback Person",
                    linkedin_url="https://linkedin.com/in/rollback",
                    email=None,
                ),
            )
            await session.rollback()
        assert (
            await connection.fetchval("SELECT count(*) FROM job_agent.contacts")
            == before_count
        )
        # Durable shared budget: many independent writers cannot exceed three credits.
        budget = DiscoveryBudget(factory)

        async def reserve(i):
            try:
                await budget.reserve("phase3_race", "phase3-race-" + str(i), 1, 3)
                return True
            except DiscoveryError:
                return False

        assert sum(await asyncio.gather(*(reserve(i) for i in range(15)))) == 3
        # A distinct target forces provider execution. Unique claim prevents duplicate
        # charges even with separate run IDs/process-equivalent service instances.
        async with factory() as session:
            target = Contact(
                company_id=company_id,
                full_name="Blair Fictional",
                role_title="Engineering Manager",
                linkedin_url="https://www.linkedin.com/in/blair-fictional/",
            )
            session.add(target)
            await session.commit()
            target_id = target.id
        apollo = FakeApollo()
        apollo.response = apollo.result(
            "completed",
            contacts=[
                person(
                    full_name="Blair Fictional",
                    role_title="Engineering Manager",
                    linkedin_url="https://www.linkedin.com/in/blair-fictional/",
                    email="blair@fictional.example.com",
                )
            ],
        )

        async def enrich(i, same_key=False):
            async with factory() as session:
                svc = ContactEnrichmentService(
                    session,
                    factory,
                    settings(),
                    {"apollo": apollo, "signalhire": FakeSignal()},
                )
                run = await svc.enrich(
                    company_id,
                    EnrichInput(
                        target_roles=["engineering_manager"],
                        allow_paid=True,
                        idempotency_key="same" if same_key else "race-" + str(i),
                    ),
                )
                return run.id

        await asyncio.gather(*(enrich(i) for i in range(8)))
        assert len(apollo.calls) == 1
        async with factory() as session:
            contact = await session.get(Contact, target_id)
            assert (
                contact.email == "blair@fictional.example.com"
                and contact.email_status == "provider_reported"
            )
            count = await session.scalar(select(func.count()).select_from(Contact))
            assert count == 2
        same_ids = await asyncio.gather(*(enrich(i, True) for i in range(5)))
        assert len(set(same_ids)) == 1
        print(
            "Phase 3 PostgreSQL PASS: 001-005 twice; preserved legacy records/public schema; RLS, FKs, unique identities, concurrent reconciliation, rollback, concurrent paid claims, idempotency and budget caps"
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
