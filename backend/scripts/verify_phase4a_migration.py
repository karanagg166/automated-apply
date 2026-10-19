"""Verify 001-006 and Phase 4A races in a disposable localhost database only."""

import asyncio
import json
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
    database = "candidate_profile_test_phase4a_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ["DATABASE_URL"] = isolated.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        os.environ["DATABASE_SCHEMA"] = "job_agent"
        os.environ["ENVIRONMENT"] = "testing"
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.integrations.connection_service import ConnectionService
        from backend.app.integrations.google_oauth import GoogleOAuth
        from backend.app.integrations.token_store import ConnectionError
        from backend.app.models.connected_account import ConnectedAccount
        from backend.app.schemas.outreach import DraftEdit, DraftInput
        from backend.app.services.outreach_drafting import (
            DraftConflict,
            OutreachDraftingService,
        )
        from backend.tests.phase2a_fakes import PROJECT
        from backend.tests.phase4a_fakes import (
            CALLBACK,
            EMAIL,
            GoogleFixture,
            oauth_settings,
            state_from,
            target,
        )

        connection = await asyncpg.connect(isolated)
        # Test real grants using realistic Supabase role names. This database/container is disposable.
        for role in ("anon", "authenticated", "service_role"):
            if not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            ):
                await connection.execute(
                    f'CREATE ROLE "{role}" NOLOGIN'
                    + (" BYPASSRLS" if role == "service_role" else "")
                )
        for path in sorted((ROOT / "supabase/migrations").glob("00[1-5]*.sql")):
            await connection.execute(path.read_text())
        profile = await connection.fetchval(
            "INSERT INTO job_agent.candidate_profiles(full_name,email,projects,verified_skills) VALUES('Alex Example','alex@example.com',$1::jsonb,'[\"Python\",\"FastAPI\"]') RETURNING id",
            json.dumps([PROJECT]),
        )
        await connection.execute(
            "INSERT INTO job_agent.candidate_resources(candidate_profile_id,resource_type,label,url,user_confirmed) VALUES($1,'resume','Resume','https://example.com/resume',true)",
            profile,
        )
        await connection.execute(
            "INSERT INTO job_agent.candidate_evidence(candidate_profile_id,evidence_type,title,content,user_confirmed) VALUES($1,'achievement','Legacy evidence','A reviewed achievement',true)",
            profile,
        )
        company = await connection.fetchval(
            "INSERT INTO job_agent.companies(name,domain) VALUES('Legacy','legacy.example.com') RETURNING id"
        )
        contact = await connection.fetchval(
            "INSERT INTO job_agent.contacts(company_id,full_name,role_title,do_not_contact,suppression_reason) VALUES($1,'Legacy suppressed','CTO',true,'Retain suppression') RETURNING id",
            company,
        )
        job = await connection.fetchval(
            "INSERT INTO job_agent.jobs(company_id,title,job_url,source_platform) VALUES($1,'Legacy engineer','https://legacy.example.com/job','manual') RETURNING id",
            company,
        )
        await connection.execute(
            "INSERT INTO job_agent.outreach_logs(job_id,contact_id,subject,body,approval_status,gmail_message_id,sent_at) VALUES($1,$2,'Legacy sent','Keep history','sent','legacy-real-message',now())",
            job,
            contact,
        )
        await connection.execute(
            "INSERT INTO job_agent.contact_evidence(contact_id,company_id,source,evidence_type,expires_at) VALUES($1,$2,'manual','human_correction',now()+interval '1 day')",
            contact,
            company,
        )
        await connection.execute(
            "INSERT INTO job_agent.discovery_monthly_budgets(provider,month,reserved) VALUES('legacy','2026-10',3)"
        )
        await connection.execute(
            "INSERT INTO job_agent.api_keys_pool(provider,account_label,secret_reference,credits_remaining) VALUES('legacy','legacy','env:UNSET_TEST_KEY',2)"
        )
        await connection.execute(
            "CREATE TABLE public.phase4a_sentinel(value text); INSERT INTO public.phase4a_sentinel VALUES('retain')"
        )
        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='job_agent' ORDER BY tablename"
        )
        snapshots = {
            r["tablename"]: [
                dict(row)
                for row in await connection.fetch(
                    f'SELECT * FROM job_agent."{r["tablename"]}" ORDER BY 1'
                )
            ]
            for r in tables
        }
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        migration = (
            ROOT / "supabase/migrations/006_mcp_gmail_outreach_foundation.sql"
        ).read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        for table, records in snapshots.items():
            current = [
                dict(r)
                for r in await connection.fetch(
                    f'SELECT * FROM job_agent."{table}" ORDER BY 1'
                )
            ]
            assert len(current) == len(records), table
            for before, after in zip(records, current, strict=True):
                assert all(after[k] == v for k, v in before.items()), table
        assert public_before == await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        assert (
            await connection.fetchval("SELECT value FROM public.phase4a_sentinel")
            == "retain"
        )
        for table in ("connected_accounts", "oauth_states", "outreach_logs"):
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass",
                "job_agent." + table,
            )
            assert not await connection.fetchval(
                "SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1",
                table,
            )
            for role in ("anon", "authenticated"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege($1,$2,'SELECT')",
                    role,
                    "job_agent." + table,
                )
            assert await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'SELECT,INSERT,UPDATE,DELETE')",
                "job_agent." + table,
            )
        # An actual unprivileged query is denied, including the encrypted column.
        await connection.execute("GRANT USAGE ON SCHEMA job_agent TO authenticated")
        await connection.execute("SET ROLE authenticated")
        try:
            await connection.fetch(
                "SELECT encrypted_refresh_token FROM job_agent.connected_accounts"
            )
            raise AssertionError("Token table publicly readable")
        except asyncpg.InsufficientPrivilegeError:
            pass
        finally:
            await connection.execute("RESET ROLE")

        engine = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_size=15,
            max_overflow=5,
            hide_parameters=True,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        settings, fake = oauth_settings(), GoogleFixture()
        async with fake.client() as http:
            google = GoogleOAuth(settings, http)
            async with factory() as session:
                state = state_from(
                    await ConnectionService(session, settings, google).start(
                        EMAIL, "browser"
                    )
                )

            async def callback_once():
                async with factory() as session:
                    try:
                        return await ConnectionService(
                            session, settings, google
                        ).callback(state, "browser", CALLBACK, "code")
                    except ConnectionError:
                        return None

            callbacks = await asyncio.gather(*(callback_once() for _ in range(10)))
            assert sum(result is not None for result in callbacks) == 1
            assert len([r for r in fake.requests if r.url.path == "/token"]) == 1
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM job_agent.connected_accounts"
                )
                == 1
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM job_agent.oauth_states WHERE consumed_at IS NOT NULL"
                )
                == 1
            )
            try:
                await connection.execute(
                    "INSERT INTO job_agent.oauth_states SELECT * FROM job_agent.oauth_states"
                )
                raise AssertionError("Duplicate OAuth state accepted")
            except asyncpg.UniqueViolationError:
                pass
            try:
                await connection.execute(
                    "UPDATE job_agent.oauth_states SET expires_at=created_at+interval '1 hour'"
                )
                raise AssertionError("Overlong OAuth expiry accepted")
            except asyncpg.CheckViolationError:
                pass
            try:
                await connection.execute(
                    "INSERT INTO job_agent.connected_accounts(provider,google_subject,account_email,status) VALUES('gmail','other','other@example.com','disconnected')"
                )
                raise AssertionError("Duplicate provider/account accepted")
            except asyncpg.UniqueViolationError:
                pass
            try:
                await connection.execute(
                    "UPDATE job_agent.connected_accounts SET encrypted_refresh_token='plaintext-refresh'"
                )
                raise AssertionError("Plaintext token accepted")
            except asyncpg.CheckViolationError:
                pass
            await connection.execute(
                "UPDATE job_agent.connected_accounts SET token_expires_at=now()-interval '1 second'"
            )

            async def refresh_once():
                async with factory() as session:
                    return await ConnectionService(
                        session, settings, google
                    ).access_token()

            assert set(await asyncio.gather(*(refresh_once() for _ in range(12)))) == {
                "fictional-access"
            }
            assert len([r for r in fake.requests if r.url.path == "/token"]) == 2
            assert await connection.fetchval(
                "SELECT last_refresh_at IS NOT NULL FROM job_agent.connected_accounts"
            )
            # Failed transaction cannot change a connection or an unrelated legacy contact.
            async with factory() as session:
                account = await session.scalar(select(ConnectedAccount))
                account.account_email = "rollback@example.com"
                await session.flush()
                await session.rollback()
            assert (
                await connection.fetchval(
                    "SELECT account_email FROM job_agent.connected_accounts"
                )
                == EMAIL
            )
            assert await connection.fetchval(
                "SELECT do_not_contact FROM job_agent.contacts WHERE id=$1", contact
            )
            # Callback already exchanging a code cannot reconnect after an owner disconnect.
            async with factory() as session:
                await ConnectionService(session, settings, google).disconnect()
                state = state_from(
                    await ConnectionService(session, settings, google).start(
                        EMAIL, "browser"
                    )
                )
            entered, release = asyncio.Event(), asyncio.Event()

            class SlowGoogle(GoogleOAuth):
                async def exchange(self, code, verifier):
                    entered.set()
                    await release.wait()
                    return await super().exchange(code, verifier)

            async def delayed_callback():
                async with factory() as session:
                    try:
                        await ConnectionService(
                            session, settings, SlowGoogle(settings, http)
                        ).callback(state, "browser", CALLBACK, "code")
                        return True
                    except ConnectionError:
                        return False

            task = asyncio.create_task(delayed_callback())
            await entered.wait()
            async with factory() as session:
                await ConnectionService(session, settings, google).disconnect()
            release.set()
            assert not await task
            assert (
                await connection.fetchval(
                    "SELECT status FROM job_agent.connected_accounts"
                )
                == "disconnected"
            )
        # Real durable draft idempotency, row locks, revisions and approval invalidation.
        async with factory() as session:
            target_contact, _, target_job, _ = await target(session)
            draft_request = DraftInput(
                contact_id=target_contact.id,
                job_id=target_job.id,
                use_llm=False,
                idempotency_key="postgres-draft-key",
            )

        async def persist():
            async with factory() as session:
                draft = await OutreachDraftingService(session, settings).create(
                    draft_request
                )
                await session.commit()
                return draft["id"]

        ids = await asyncio.gather(*(persist() for _ in range(8)))
        assert len(set(ids)) == 1
        async with factory() as session:
            rollback_request = draft_request.model_copy(
                update={"idempotency_key": "rollback-draft-key"}
            )
            await OutreachDraftingService(session, settings).create(rollback_request)
            await session.rollback()
        assert not await connection.fetchval(
            "SELECT count(*) FROM job_agent.outreach_logs WHERE idempotency_key='rollback-draft-key'"
        )
        async with factory() as session:
            service = OutreachDraftingService(session, settings)
            draft = await service.read(ids[0])
            approved = await service.decide(ids[0], draft["draft_revision"], True)
            assert approved["eligibility"]["approval_current"], approved
            await session.commit()
        # Raw SQL editing is protected too, independently of application code.
        await connection.execute(
            "UPDATE job_agent.outreach_logs SET body=body || ' A material edit.' WHERE id=$1",
            ids[0],
        )
        record = await connection.fetchrow(
            "SELECT approval_status,approved_at,approval_hash,approved_revision,draft_revision FROM job_agent.outreach_logs WHERE id=$1",
            ids[0],
        )
        assert (
            record["approval_status"] == "pending_approval"
            and record["approved_at"] is None
            and record["approval_hash"] is None
        )
        assert record["draft_revision"] == approved["draft_revision"] + 1
        try:
            await connection.execute(
                "UPDATE job_agent.outreach_logs SET approval_status='approved' WHERE id=$1",
                ids[0],
            )
            raise AssertionError("Unversioned approval accepted")
        except asyncpg.RaiseError:
            pass
        try:
            await connection.execute(
                "UPDATE job_agent.outreach_logs SET approval_status='sent',gmail_message_id='fake' WHERE id=$1",
                ids[0],
            )
            raise AssertionError("Fake sending accepted")
        except asyncpg.RaiseError:
            pass

        # Concurrent edits: only one expected revision may win.
        async def edit_once(i):
            async with factory() as session:
                try:
                    await OutreachDraftingService(session, settings).edit(
                        ids[0],
                        DraftEdit(
                            expected_revision=record["draft_revision"],
                            body=f"Edited {i}",
                        ),
                    )
                    await session.commit()
                    return True
                except DraftConflict:
                    return False

        assert sum(await asyncio.gather(*(edit_once(i) for i in range(8)))) == 1
        assert (
            await connection.fetchval(
                "SELECT gmail_message_id FROM job_agent.outreach_logs WHERE subject='Legacy sent'"
            )
            == "legacy-real-message"
        )
        print(
            "Phase 4A PostgreSQL PASS: 001-006 (006 twice), all legacy records/public preserved; RLS/grants, encrypted-only tokens, unique connections, single-use callback races, serialized refresh, disconnect race, rollback, idempotent drafts, revision races, approval invalidation, no fake send"
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
