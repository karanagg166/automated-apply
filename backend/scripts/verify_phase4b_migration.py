"""Offline 001–007 migration and independent-worker send verification on localhost only."""

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
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase4b_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ["DATABASE_URL"] = isolated.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        os.environ["DATABASE_SCHEMA"], os.environ["ENVIRONMENT"] = (
            "job_agent",
            "testing",
        )
        import httpx
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.integrations.connection_service import ConnectionService
        from backend.app.integrations.gmail.schemas import SendFailure
        from backend.app.integrations.google_oauth import GoogleOAuth
        from backend.app.models.connected_account import OAuthState
        from backend.app.models.outreach_send import OutreachSendAttempt
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.gmail_sending import GmailSendingService
        from backend.app.services.outreach_drafting import DraftConflict
        from backend.tests.phase2a_fakes import PROJECT
        from backend.tests.phase4b_fakes import (
            SendFixture,
            approved_target,
            bundle,
            connect_sender,
            request_from,
        )

        async def no_live_http(*args, **kwargs):
            raise AssertionError("Live HTTP forbidden in migration tests")

        httpx.AsyncHTTPTransport.handle_async_request = no_live_http
        connection = await asyncpg.connect(isolated)
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
        legacy = await connection.fetchval("""INSERT INTO job_agent.outreach_logs(subject,body,approval_status,gmail_message_id,sent_at)
            VALUES('Historic sent','Preserve text','sent','historic-provider-id',now()) RETURNING id""")
        await connection.execute(
            (
                ROOT / "supabase/migrations/006_mcp_gmail_outreach_foundation.sql"
            ).read_text()
        )
        before = await connection.fetch(
            "SELECT * FROM job_agent.outreach_logs ORDER BY id"
        )
        await connection.execute(
            "CREATE TABLE public.phase4b_sentinel(value text); INSERT INTO public.phase4b_sentinel VALUES('keep')"
        )
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        migration = (ROOT / "supabase/migrations/007_gmail_sending.sql").read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        assert before == await connection.fetch(
            "SELECT * FROM job_agent.outreach_logs ORDER BY id"
        )
        assert public_before == await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        assert (
            await connection.fetchval("SELECT value FROM public.phase4b_sentinel")
            == "keep"
        )
        for table in ("outreach_send_confirmations", "outreach_send_attempts"):
            name = "job_agent." + table
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass", name
            )
            assert not await connection.fetchval(
                "SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1",
                table,
            )
            for role in ("anon", "authenticated"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege($1,$2,'SELECT,INSERT,UPDATE,DELETE')",
                    role,
                    name,
                )
            assert await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'SELECT,INSERT,UPDATE')",
                name,
            )
            assert not await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'DELETE')", name
            )
        await connection.execute(
            "GRANT USAGE ON SCHEMA job_agent TO authenticated; SET ROLE authenticated"
        )
        try:
            await connection.fetch("SELECT * FROM job_agent.outreach_send_attempts")
            raise AssertionError("Client role can access send history")
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
        settings, google = await bundle()
        sender = SendFixture()
        async with google.client() as http:

            def service(session):
                return GmailSendingService(
                    session,
                    settings,
                    ConnectionService(session, settings, GoogleOAuth(settings, http)),
                    sender,
                )

            async with factory() as session:
                await CandidateProfileRepository(session).create_primary_profile(
                    CandidateProfileCreate(
                        full_name="Alex Example",
                        email="alex@example.com",
                        verified_skills=["Python", "FastAPI"],
                        projects=[PROJECT],
                    )
                )
                await session.commit()
                await connect_sender(session, settings, google, http)
                draft, contact, *_ = await approved_target(session, settings)
                preview = await service(session).preview(draft["id"])
            request = request_from(preview)

            async def send_once(key=draft["id"], data=request):
                async with factory() as session:
                    try:
                        return await service(session).send(key, data)
                    except DraftConflict:
                        await session.rollback()
                        return None

            results = await asyncio.gather(*(send_once() for _ in range(10)))
            assert all(
                r and r["status"] in {"prepared", "attempting", "accepted_by_gmail"}
                for r in results
            ), [r and r["status"] for r in results]
            assert any(r["status"] == "accepted_by_gmail" for r in results)
            assert len({r["id"] for r in results}) == 1 and len(sender.calls) == 1
            attempt_id = results[0]["id"]
            accepted = await connection.fetchrow(
                "SELECT * FROM job_agent.outreach_send_attempts WHERE id=$1", attempt_id
            )
            assert accepted["draft_revision"] == draft["draft_revision"]
            assert (
                await connection.fetchval(
                    "SELECT draft_revision FROM job_agent.outreach_logs WHERE id=$1",
                    draft["id"],
                )
                == draft["draft_revision"]
            )
            assert not await send_once(
                data=request.model_copy(
                    update={"idempotency_key": "different-human-key"}
                )
            )

            # Illegal backend writes cannot mutate identities, bypass approval, erase or fake history.
            async def rejected(sql, *args):
                try:
                    await connection.execute(sql, *args)
                except (
                    asyncpg.RaiseError,
                    asyncpg.CheckViolationError,
                    asyncpg.UniqueViolationError,
                    asyncpg.ForeignKeyViolationError,
                ):
                    return
                raise AssertionError("Invariant write was accepted: " + sql)

            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET recipient_email='other@example.com' WHERE id=$1",
                attempt_id,
            )
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET gmail_message_id='fabricated' WHERE id=$1",
                attempt_id,
            )
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET status='attempting' WHERE id=$1",
                attempt_id,
            )
            await rejected(
                "DELETE FROM job_agent.outreach_send_attempts WHERE id=$1", attempt_id
            )
            await rejected(
                "UPDATE job_agent.outreach_logs SET sent_at=now(),gmail_message_id='fabricated' WHERE id=$1",
                draft["id"],
            )
            await rejected(
                "INSERT INTO job_agent.outreach_logs(subject,body,approval_status,gmail_message_id,sent_at) VALUES('fake','fake','sent','fake',now())"
            )
            await rejected(
                "UPDATE job_agent.outreach_send_confirmations SET consumed_at=NULL WHERE draft_id=$1",
                draft["id"],
            )
            # Later suppression preserves immutable acceptance history.
            await connection.execute(
                "UPDATE job_agent.contacts SET do_not_contact=true WHERE id=$1",
                contact.id,
            )
            assert accepted == await connection.fetchrow(
                "SELECT * FROM job_agent.outreach_send_attempts WHERE id=$1", attempt_id
            )
            # Even raw edits creating a new revision cannot permit another send of this draft.
            await connection.execute(
                "UPDATE job_agent.outreach_logs SET body=body || ' material edit' WHERE id=$1",
                draft["id"],
            )
            row = await connection.fetchrow(
                "SELECT approval_status,approval_hash,approved_revision FROM job_agent.outreach_logs WHERE id=$1",
                draft["id"],
            )
            assert (
                row["approval_status"] == "pending_approval"
                and row["approval_hash"] is None
                and row["approved_revision"] is None
            )
            assert not await send_once(
                data=request.model_copy(
                    update={"idempotency_key": "another-revision-key"}
                )
            )

            # Atomic confirmation consumption from independent connections and rollback.
            async with factory() as session:
                second, *_ = await approved_target(session, settings, suffix="two")
                second_preview = await service(session).preview(second["id"])
            confirmation = await connection.fetchrow(
                "SELECT * FROM job_agent.outreach_send_confirmations WHERE draft_id=$1",
                second["id"],
            )
            transaction = connection.transaction()
            await transaction.start()
            await connection.execute(
                "UPDATE job_agent.outreach_send_confirmations SET consumed_at=now() WHERE token_hash=$1",
                confirmation["token_hash"],
            )
            await transaction.rollback()
            assert (
                await connection.fetchval(
                    "SELECT consumed_at FROM job_agent.outreach_send_confirmations WHERE token_hash=$1",
                    confirmation["token_hash"],
                )
                is None
            )

            async def consume():
                worker = await asyncpg.connect(isolated)
                try:
                    return await worker.fetchval(
                        "UPDATE job_agent.outreach_send_confirmations SET consumed_at=now() WHERE token_hash=$1 AND consumed_at IS NULL RETURNING token_hash",
                        confirmation["token_hash"],
                    )
                finally:
                    await worker.close()

            assert (
                sum(
                    r is not None
                    for r in await asyncio.gather(*(consume() for _ in range(8)))
                )
                == 1
            )
            assert not await send_once(
                second["id"], request_from(second_preview, "consumed-human-key")
            )

            # Parallel upgrade starts share durable generations, preserving the active sender.
            async def upgrade_start():
                async with factory() as session:
                    conn = service(session).connection
                    return await conn.start(
                        "secondary@example.com", "upgrade-browser", send=True
                    )

            starts = await asyncio.gather(*(upgrade_start() for _ in range(4)))
            async with factory() as session:
                account = await service(session).connection.account()
                intents = (
                    await session.scalars(
                        select(OAuthState).where(
                            OAuthState.authorization_mode == "send",
                            OAuthState.consumed_at.is_(None),
                        )
                    )
                ).all()
                assert (
                    sum(
                        i.connection_generation == account.token_generation
                        for i in intents
                    )
                    == 1
                )
                await session.rollback()

            from backend.app.integrations.token_store import ConnectionError
            from backend.tests.phase4a_fakes import CALLBACK, state_from

            async def upgrade_callback(start):
                async with factory() as session:
                    try:
                        return await service(session).connection.callback(
                            state_from(start),
                            "upgrade-browser",
                            CALLBACK,
                            "upgrade-code",
                        )
                    except ConnectionError:
                        await session.rollback()
                        return None

            callbacks = await asyncio.gather(
                *(upgrade_callback(start) for start in starts)
            )
            assert sum(result is not None for result in callbacks) == 1

            # Different human request keys racing on the same unattempted draft still send once.
            settings.GMAIL_SEND_MAX_PER_HOUR = 20
            settings.GMAIL_SEND_MAX_PER_DAY = 100
            async with factory() as session:
                raced, *_ = await approved_target(session, settings, suffix="racekeys")
                raced_preview = await service(session).preview(raced["id"])
            races = await asyncio.gather(
                *(
                    send_once(
                        raced["id"], request_from(raced_preview, f"race-human-key-{i}")
                    )
                    for i in range(8)
                )
            )
            assert sum(result is not None for result in races) == 1
            assert len(sender.calls) == 2

            # Rollback between consent consumption and claim commit leaves both unclaimed.
            async with factory() as session:
                rolled_back, *_ = await approved_target(
                    session, settings, suffix="rollback"
                )
                rollback_preview = await service(session).preview(rolled_back["id"])
                original_commit = session.commit

                class SimulatedCrash(BaseException):
                    pass

                async def reject_claim_commit():
                    if await session.scalar(
                        select(OutreachSendAttempt.id).where(
                            OutreachSendAttempt.draft_id == rolled_back["id"]
                        )
                    ):
                        raise SimulatedCrash()
                    await original_commit()

                session.commit = reject_claim_commit
                try:
                    await service(session).send(
                        rolled_back["id"],
                        request_from(rollback_preview, "rollback-human-key"),
                    )
                    raise AssertionError("Crash was not injected")
                except SimulatedCrash:
                    await session.rollback()
                finally:
                    session.commit = original_commit
            assert not await connection.fetchval(
                "SELECT count(*) FROM job_agent.outreach_send_attempts WHERE draft_id=$1",
                rolled_back["id"],
            )
            assert (
                await connection.fetchval(
                    "SELECT consumed_at FROM job_agent.outreach_send_confirmations WHERE draft_id=$1",
                    rolled_back["id"],
                )
                is None
            )
            assert len(sender.calls) == 2

            # A restarted process sees durable uncertainty after a provider-side crash.
            from datetime import timedelta

            from backend.app.services import gmail_sending as sending_module

            async with factory() as session:
                interrupted, *_ = await approved_target(
                    session, settings, suffix="interrupted"
                )
                interrupted_preview = await service(session).preview(interrupted["id"])
            interrupted_request = request_from(
                interrupted_preview, "interrupted-human-key"
            )
            sender.failure = SimulatedCrash()
            try:
                await send_once(interrupted["id"], interrupted_request)
                raise AssertionError("Provider-side crash was not injected")
            except SimulatedCrash:
                pass
            sender.failure = None
            interrupted_attempt = await connection.fetchrow(
                "SELECT id,status FROM job_agent.outreach_send_attempts WHERE draft_id=$1",
                interrupted["id"],
            )
            assert interrupted_attempt["status"] == "attempting"
            real_now = sending_module.now
            try:
                sending_module.now = lambda: real_now() + timedelta(minutes=5)
                async with factory() as session:
                    recovered = await service(session).status(interrupted_attempt["id"])
                    assert (
                        recovered["status"] == "outcome_unknown"
                        and recovered["reconciliation_required"]
                    )
            finally:
                sending_module.now = real_now
            assert (await send_once(interrupted["id"], interrupted_request))[
                "status"
            ] == "outcome_unknown"
            assert len(sender.calls) == 3

            # Distinct-draft cap race. Preview all first; only one more reservation may commit.
            settings.GMAIL_SEND_MAX_PER_HOUR = 20
            settings.GMAIL_SEND_MAX_PER_DAY = 100
            requests = []
            async with factory() as session:
                for index in range(4):
                    next_draft, *_ = await approved_target(
                        session, settings, suffix=f"limit{index}"
                    )
                    next_preview = await service(session).preview(next_draft["id"])
                    requests.append(
                        (
                            next_draft["id"],
                            request_from(next_preview, f"cap-human-key-{index}"),
                        )
                    )
            before_count = await connection.fetchval(
                "SELECT count(*) FROM job_agent.outreach_send_attempts"
            )
            before_calls = len(sender.calls)
            settings.GMAIL_SEND_MAX_PER_HOUR = before_count + 1
            sender.failure = SendFailure("transmission_outcome_unknown", uncertain=True)
            outcomes = await asyncio.gather(
                *(send_once(key, data) for key, data in requests)
            )
            assert sum(r is not None for r in outcomes) == 1, outcomes
            assert next(r for r in outcomes if r)["status"] == "outcome_unknown"
            assert len(sender.calls) == before_calls + 1
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM job_agent.outreach_send_attempts"
                )
                == before_count + 1
            )
            # Unknown outcome cannot be silently retried or fabricated as accepted.
            unknown = next(r for r in outcomes if r)
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET status='attempting' WHERE id=$1",
                unknown["id"],
            )
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET status='accepted_by_gmail',gmail_message_id='fake',accepted_at=now(),reconciliation_required=false WHERE id=$1",
                unknown["id"],
            )
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET status='manually_reconciled',reconciliation_required=false WHERE id=$1",
                unknown["id"],
            )
            # Explicit audited reconciliation closes an unknown outcome; it never opens a resend path.
            await connection.execute(
                """UPDATE job_agent.outreach_send_attempts SET status='manually_reconciled',reconciliation_required=false,
                reconciled_by='owner',reconciled_at=now(),reconciliation_note='Owner inspected the sender mailbox; no resend authorized.' WHERE id=$1""",
                unknown["id"],
            )
            await rejected(
                "UPDATE job_agent.outreach_send_attempts SET status='prepared' WHERE id=$1",
                unknown["id"],
            )
            # All audit rows survive replay and unrelated legacy data remains unchanged.
            snapshots = {
                table: await connection.fetch(
                    f'SELECT * FROM job_agent."{table}" ORDER BY 1'
                )
                for table in (
                    "outreach_logs",
                    "connected_accounts",
                    "oauth_states",
                    "outreach_send_confirmations",
                    "outreach_send_attempts",
                )
            }
            await connection.execute(migration)
            for table, records in snapshots.items():
                assert records == await connection.fetch(
                    f'SELECT * FROM job_agent."{table}" ORDER BY 1'
                )
            assert (
                await connection.fetchval(
                    "SELECT gmail_message_id FROM job_agent.outreach_logs WHERE id=$1",
                    legacy,
                )
                == "historic-provider-id"
            )
        print(
            "Phase 4B PostgreSQL PASS: 001–007, replay/data/public preservation, RLS/grants, exact consent, unique reservation, 10-worker idempotency, replay/rollback, durable concurrent caps/unknown accounting, upgrade serialization, trigger invariants and audited reconciliation; no live HTTP"
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
