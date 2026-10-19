"""Verify 001–008 and independent-worker packet races in a disposable localhost database."""

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
    database = "candidate_profile_test_phase5a_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ.update(
            DATABASE_URL=isolated.replace("postgresql://", "postgresql+asyncpg://", 1),
            DATABASE_SCHEMA="job_agent",
            ENVIRONMENT="testing",
            GEMINI_API_KEY="",
            LLM_MODEL="",
            GMAIL_SENDING_ENABLED="false",
            MCP_REMOTE_ENABLED="false",
        )
        import httpx
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.applications import (
            AnswerEdit,
            CreatePacket,
            PacketEdit,
            QuestionInput,
            RevisionInput,
            SubmissionInput,
            TrackingInput,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate
        from backend.app.services.application_answer_service import (
            ApplicationAnswerService,
        )
        from backend.app.services.applications.base import ApplicationConflict
        from backend.app.services.applications.review import ApplicationReview
        from backend.app.services.applications.service import ApplicationPacketService
        from backend.app.services.applications.tracker import ApplicationTracker
        from backend.tests.phase2a_fakes import PROJECT, FakeProvider
        from backend.tests.phase5a_fakes import approve, target

        async def no_http(*args, **kwargs):
            raise AssertionError("Live HTTP forbidden in application verification")

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
        for path in sorted((ROOT / "supabase/migrations").glob("00[1-7]*.sql")):
            await connection.execute(path.read_text())
        await connection.execute(
            "CREATE TABLE public.phase5a_sentinel(value text); INSERT INTO public.phase5a_sentinel VALUES('preserve')"
        )
        public_before = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        engine = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_size=15,
            max_overflow=5,
            hide_parameters=True,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(
                CandidateProfileCreate(
                    full_name="Alex Example",
                    email="alex@example.com",
                    projects=[PROJECT],
                    github_url="https://github.com/example",
                    verified_skills=["Python", "FastAPI"],
                    preferences={"notice_period_days": 30},
                )
            )
            job, resume = await target(session, profile)
            job_id, profile_id, resume_id = job.id, profile.id, resume.id
        await connection.execute(
            "INSERT INTO job_agent.contacts(company_id,full_name,role_title,email) SELECT company_id,'Example Recruiter','Recruiter','recruiter@example.org' FROM job_agent.jobs WHERE id=$1",
            job_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.candidate_evidence(candidate_profile_id,evidence_type,title,content,user_confirmed) VALUES($1,'experience','Example work','I implemented authentication.',true)",
            profile_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.application_answer_drafts(candidate_profile_id,job_id,question,answer,question_category,writing_style,candidate_profile_version) VALUES($1,$2,'Email','alex@example.com','personal_details','professional',1)",
            profile_id,
            job_id,
        )
        await connection.execute(
            "INSERT INTO job_agent.connected_accounts(provider,google_subject,account_email,status) VALUES('gmail','fictional-subject','mailbox@example.org','disconnected')"
        )
        await connection.execute(
            "INSERT INTO job_agent.outreach_logs(subject,body) VALUES('Historic outreach','Preserve this factual draft')"
        )
        tables = [
            r[0]
            for r in await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='job_agent' ORDER BY tablename"
            )
        ]

        async def rows(table):
            return await connection.fetchval(
                f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM job_agent.\"{table}\" t"
            )

        before = {t: await rows(t) for t in tables}
        migration = (
            ROOT / "supabase/migrations/008_application_preparation.sql"
        ).read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        assert before == {t: await rows(t) for t in tables}
        assert public_before == await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        assert (
            await connection.fetchval("SELECT value FROM public.phase5a_sentinel")
            == "preserve"
        )
        new_tables = (
            "application_packets",
            "application_packet_fields",
            "application_events",
            "application_submission_evidence",
        )
        for table in new_tables:
            name = "job_agent." + table
            assert await connection.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass", name
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1",
                    table,
                )
                == 0
            )
            for role in ("anon", "authenticated"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege($1,$2,'SELECT,INSERT,UPDATE,DELETE')",
                    role,
                    name,
                )
            assert await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'SELECT,INSERT')", name
            )
            assert not await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'DELETE')", name
            )
            assert await connection.fetchval(
                "SELECT has_table_privilege('service_role',$1,'UPDATE')", name
            ) == (table in new_tables[:2])
        await connection.execute(
            "GRANT USAGE ON SCHEMA job_agent TO authenticated; SET ROLE authenticated"
        )
        try:
            await connection.fetch("SELECT * FROM job_agent.application_packets")
            raise AssertionError("Client role has application access")
        except asyncpg.InsufficientPrivilegeError:
            pass
        finally:
            await connection.execute("RESET ROLE")

        async def create_once():
            async with factory() as session:
                result = await ApplicationPacketService(session).create(
                    job_id, CreatePacket(idempotency_key="postgres-packet-001")
                )
                await session.commit()
                return result

        packets = await asyncio.gather(*(create_once() for _ in range(8)))
        assert len({p.id for p in packets}) == 1
        packet = packets[0]
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.application_events"
            )
            == 1
        )

        async def edit_once(index):
            async with factory() as session:
                try:
                    await ApplicationPacketService(session).edit_answer(
                        packet.id,
                        packet.fields[0].id,
                        AnswerEdit(expected_revision=1, answer=f"Alex Example {index}"),
                    )
                    await session.commit()
                    return True
                except ApplicationConflict:
                    await session.rollback()
                    return False

        assert sum(await asyncio.gather(*(edit_once(i) for i in range(8)))) == 1
        async with factory() as session:
            service = ApplicationPacketService(session)
            current = await service.read(packet.id)
            current = await approve(service, current)
            assert (
                await ApplicationReview(service).handoff(packet.id)
            ).submitted is False
            assert (
                await connection.fetchval(
                    "SELECT status FROM job_agent.jobs WHERE id=$1", job_id
                )
                == "discovered"
            )

        # A handoff holds a consistent parent/context snapshot until its transaction ends.
        async with factory() as reader:
            handoff = await ApplicationReview(ApplicationPacketService(reader)).handoff(
                packet.id
            )

            async def concurrent_edit():
                async with factory() as writer:
                    await ApplicationPacketService(writer).edit_answer(
                        packet.id,
                        packet.fields[0].id,
                        AnswerEdit(
                            expected_revision=handoff.revision,
                            answer="Alex Consistent Example",
                        ),
                    )
                    await writer.commit()

            task = asyncio.create_task(concurrent_edit())
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                raise AssertionError("Writer modified an in-use handoff snapshot")
            except TimeoutError:
                pass
            await reader.commit()
            await task
        async with factory() as session:
            service = ApplicationPacketService(session)
            await approve(service, await service.read(packet.id))

        # Direct material edits invalidate approval and advance revisions independently of ORM.
        await connection.execute(
            "UPDATE job_agent.application_packet_fields SET human_answer='Alex Fictional Example' WHERE id=$1",
            packet.fields[0].id,
        )
        assert await connection.fetchval(
            "SELECT approved_revision IS NULL FROM job_agent.application_packets WHERE id=$1",
            packet.id,
        )
        assert (
            await connection.fetchval(
                "SELECT review_status FROM job_agent.application_packet_fields WHERE id=$1",
                packet.fields[0].id,
            )
            == "pending"
        )
        async with factory() as session:
            service = ApplicationPacketService(session)
            current = await approve(service, await service.read(packet.id))
            saved_revision = current.revision
        # Saved evidence changes cannot use an old approval; refresh clears prior edits.
        await connection.execute(
            "UPDATE job_agent.candidate_evidence SET content='I implemented signed token authentication.' WHERE candidate_profile_id=$1",
            profile_id,
        )
        async with factory() as session:
            service = ApplicationPacketService(session)
            assert (await service.read(packet.id)).readiness.stale
            try:
                await ApplicationReview(service).handoff(packet.id)
                raise AssertionError("Stale handoff allowed")
            except ApplicationConflict:
                pass
            current = await service.edit(
                packet.id,
                PacketEdit(expected_revision=saved_revision, refresh_saved_data=True),
            )
            await session.commit()
            current = await approve(service, current)
            current = await ApplicationTracker(service).track(
                packet.id,
                TrackingInput(
                    expected_revision=current.revision,
                    lifecycle_state="external_application_opened",
                ),
            )
            await session.commit()
            assert current.tracking_state == "not_applied"

        # Roll back after an entire successful mutation: packet, field and event all revert.
        baseline = await connection.fetchval(
            "SELECT revision FROM job_agent.application_packets WHERE id=$1", packet.id
        )
        event_count = await connection.fetchval(
            "SELECT count(*) FROM job_agent.application_events"
        )
        async with factory() as session:
            await ApplicationPacketService(session).edit_answer(
                packet.id,
                packet.fields[0].id,
                AnswerEdit(expected_revision=baseline, answer="Rolled Back Example"),
            )
            await session.rollback()
        assert (
            await connection.fetchval(
                "SELECT revision FROM job_agent.application_packets WHERE id=$1",
                packet.id,
            )
            == baseline
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.application_events"
            )
            == event_count
        )

        async def rejects(statement, *args):
            try:
                await connection.execute(statement, *args)
                raise AssertionError(
                    "Invalid database mutation was accepted: " + statement
                )
            except asyncpg.PostgresError:
                pass

        await rejects(
            "UPDATE job_agent.application_packets SET lifecycle_state='provider_confirmed_submitted' WHERE id=$1",
            packet.id,
        )
        await rejects(
            "UPDATE job_agent.application_packets SET lifecycle_state='user_reported_submitted' WHERE id=$1",
            packet.id,
        )
        await rejects(
            "UPDATE job_agent.application_packets SET tracking_state='applied_manually' WHERE id=$1",
            packet.id,
        )
        await rejects(
            "DELETE FROM job_agent.candidate_resources WHERE id=$1", resume_id
        )
        await rejects(
            "UPDATE job_agent.application_packets SET resume_resource_id=$1 WHERE id=$2",
            uuid.uuid4(),
            packet.id,
        )
        await rejects(
            "UPDATE job_agent.application_events SET note='rewrite' WHERE packet_id=$1",
            packet.id,
        )
        await rejects(
            "DELETE FROM job_agent.application_events WHERE packet_id=$1", packet.id
        )

        request = SubmissionInput(
            expected_revision=baseline,
            idempotency_key="postgres-submitted-001",
            human_confirmed=True,
            confirmation="I submitted this application on the official website",
            receipt_reference="Fictional receipt",
        )

        async def report_once():
            async with factory() as session:
                result = await ApplicationTracker(
                    ApplicationPacketService(session)
                ).report(packet.id, request)
                await session.commit()
                return result.id

        assert len(set(await asyncio.gather(*(report_once() for _ in range(8))))) == 1
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.application_submission_evidence"
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM job_agent.application_events WHERE event_type='user_reported_submission'"
            )
            == 1
        )
        await rejects(
            "UPDATE job_agent.application_submission_evidence SET receipt_reference='rewrite' WHERE packet_id=$1",
            packet.id,
        )
        await rejects(
            "DELETE FROM job_agent.application_submission_evidence WHERE packet_id=$1",
            packet.id,
        )
        await rejects(
            "UPDATE job_agent.application_packets SET snapshot='{}' WHERE id=$1",
            packet.id,
        )
        assert (
            await connection.fetchval(
                "SELECT status FROM job_agent.jobs WHERE id=$1", job_id
            )
            == "discovered"
        )

        # A separate job exercises grounded Gemini composition with an injected offline provider.
        async with factory() as session:
            from backend.app.core.config import Settings
            from backend.app.models.job import Job

            other = Job(
                title="Example Python Engineer",
                source_platform="naukri",
                job_url="https://www.naukri.com/example-second-job",
                application_url="https://example.org/apply",
                company_id=job.company_id,
                description="Python backend services",
            )
            session.add(other)
            await session.commit()
            settings = Settings(
                _env_file=None,
                GEMINI_API_KEY="fictional-key",
                LLM_MODEL="gemini-test-model",
            )
            service = ApplicationPacketService(
                session, ApplicationAnswerService(session, settings, FakeProvider())
            )
            narrative = await service.create(
                other.id,
                CreatePacket(
                    idempotency_key="postgres-narrative-001",
                    questions=[
                        QuestionInput(question="Describe your most challenging project")
                    ],
                ),
            )
            await session.commit()
            narrative = await service.generate(
                narrative.id,
                narrative.fields[-1].id,
                RevisionInput(expected_revision=1),
            )
            await session.commit()
            assert narrative.fields[-1].validation_status == "draft_ready"
            narrative = await approve(service, narrative)
            assert (
                (await ApplicationReview(service).handoff(narrative.id))
                .fields[-1]
                .effective_answer
            )
        assert before["connected_accounts"] == await rows("connected_accounts")
        assert before["outreach_logs"] == await rows("outreach_logs")
        print(
            "Phase 5A PostgreSQL PASS: 001-008 (008 twice); all legacy rows/public preserved; RLS/grants; FK retention; 8-worker creation/edit/report races; exact approval, stale evidence, manual handoff, rollback, immutable history, no false submission; offline grounded narrative"
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
