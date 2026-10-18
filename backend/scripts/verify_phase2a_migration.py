"""Phase 2A verification in a uniquely named disposable local PostgreSQL database."""
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
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path != "/candidate_profile_test":
        raise ValueError("Only a local candidate_profile_test database is permitted")
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_phase2a_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated_url = urlunsplit(parsed._replace(path="/" + database))
    connection = engine = None
    try:
        os.environ["DATABASE_URL"] = isolated_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        os.environ["DATABASE_SCHEMA"] = "job_agent"
        os.environ["ENVIRONMENT"] = "testing"
        os.environ["GEMINI_API_KEY"] = ""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from backend.app.ai.base import ProviderError
        from backend.app.ai.schemas import AnswerGenerationResult, GenerateRequest
        from backend.app.ai.usage import LLMUsageManager
        from backend.app.core.config import Settings
        from backend.app.models.application_answer import LLMMonthlyUsage
        from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
        from backend.app.repositories.candidate_profile import CandidateProfileRepository, ProfileConflictError, ProfileNotFoundError
        from backend.app.schemas.candidate_resources import EvidencePatch, EvidenceWrite, ResourceWrite
        from backend.app.schemas.candidate_profile import CandidateProfileUpdate
        from backend.app.services.application_answer_service import ApplicationAnswerService
        from backend.tests.phase2a_fakes import FakeProvider
        connection = await asyncpg.connect(isolated_url)
        for name in ["001_initial_schema.sql", "002_candidate_profile.sql"]:
            await connection.execute((ROOT / "supabase/migrations" / name).read_text())
        await connection.execute("CREATE TABLE public.phase2a_sentinel(value text); INSERT INTO public.phase2a_sentinel VALUES ('preserve')")
        cid = await connection.fetchval("INSERT INTO job_agent.companies(name) VALUES('Existing Example') RETURNING id")
        pid = await connection.fetchval("INSERT INTO job_agent.candidate_profiles(full_name,email,version) VALUES('Alex Example','alex@example.com',7) RETURNING id")
        before_company = await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", cid)
        before_profile = await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.candidate_profiles c WHERE id=$1", pid)
        public_before = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        migration = (ROOT / "supabase/migrations/003_candidate_resources_and_answer_drafts.sql").read_text()
        await connection.execute(migration)
        await connection.execute(migration)
        assert await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", cid) == before_company
        assert await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.candidate_profiles c WHERE id=$1", pid) == before_profile
        assert await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename") == public_before
        for table in ["candidate_resources", "candidate_evidence", "application_answer_drafts", "llm_monthly_usage"]:
            assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass", f"job_agent.{table}")
            assert await connection.fetchval("SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename=$1", table) == 0
        engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            repo = CandidateKnowledgeRepository(session)
            profile = await repo.profile()
            item = await repo.save_resource(ResourceWrite(resource_type="resume", label="General resume", url="https://drive.google.com/file/d/example/view", is_primary=True, user_confirmed=True))
            rid = item.id
            evidence = await repo.add_evidence(EvidenceWrite(evidence_type="experience", title="Authentication", content="I implemented authentication with Python.", user_confirmed=True))
            eid = evidence.id
            await session.commit()
            assert profile.version == 7
        async with factory() as session:
            repo = CandidateKnowledgeRepository(session)
            assert len(await repo.resources(pid)) == 1 and len(await repo.evidence(pid)) == 1
            await repo.patch_evidence(eid, EvidencePatch(content="Rolled back"))
            await session.rollback()
        assert await connection.fetchval("SELECT content FROM job_agent.candidate_evidence WHERE id=$1", eid) == "I implemented authentication with Python."
        async with factory() as session:
            repo = CandidateKnowledgeRepository(session)
            try:
                await repo.save_resource(ResourceWrite(resource_type="resume", label="Duplicate", url="https://example.com/another", is_primary=True))
            except ProfileConflictError:
                await session.rollback()
            else:
                raise AssertionError("Conflicting primary accepted")
        # Real concurrent primary writers: a database index, not an application check.
        await connection.execute("UPDATE job_agent.candidate_resources SET is_primary=false")
        async def primary_writer(suffix):
            async with factory() as session:
                try:
                    await CandidateKnowledgeRepository(session).save_resource(ResourceWrite(resource_type="resume", label="Candidate resume", url=f"https://example.com/{suffix}", is_primary=True))
                    await session.commit()
                    return "saved"
                except ProfileConflictError:
                    await session.rollback()
                    return "conflict"
        assert sorted(await asyncio.gather(primary_writer("one"), primary_writer("two"))) == ["conflict", "saved"]
        try:
            await connection.execute("INSERT INTO job_agent.candidate_resources(candidate_profile_id,resource_type,label,url) VALUES($1,'resume','Bad FK','https://example.com/fk')", uuid.uuid4())
        except asyncpg.ForeignKeyViolationError:
            pass
        else:
            raise AssertionError("Broken FK accepted")
        async with factory() as session:
            repo = CandidateKnowledgeRepository(session)
            profile = await repo.profile()
            result = AnswerGenerationResult(question_type="short_text", status="draft_ready", answer="A factual draft.")
            draft = await repo.save_draft(profile, GenerateRequest(question="Professional summary"), result)
            draft_id = draft.id
            await session.commit()
            await repo.review_draft(draft_id, "reviewed")
            await session.commit()
            assert draft.review_status == "reviewed"
            await CandidateProfileRepository(session).update_primary_profile(CandidateProfileUpdate(summary="Updated verified summary"), 7)
            await session.commit()
        async with factory() as session:
            repo = CandidateKnowledgeRepository(session)
            profile = await repo.profile()
            draft = (await repo.drafts(profile.id))[0]
            assert draft.candidate_profile_version == 7 and profile.version == 8
            assert draft.review_status == "reviewed" and draft.answer == "A factual draft."
            await repo.review_draft(draft_id, "discarded")
            await session.commit()
        # Atomic quota across real independent transactions, surviving unrelated rollbacks.
        settings = Settings(_env_file=None, LLM_MONTHLY_MAX_REQUESTS=3)
        manager = LLMUsageManager(factory, settings)
        async def reserve():
            try:
                return await manager.reserve()
            except ProviderError as exc:
                return exc.code
        reservations = await asyncio.gather(*(reserve() for _ in range(12)))
        assert reservations.count("monthly_request_limit") == 9
        assert await connection.fetchval("SELECT requests FROM job_agent.llm_monthly_usage") == 3
        # Budget reservations survive a failed draft transaction and invalid model responses.
        await connection.execute("DELETE FROM job_agent.llm_monthly_usage")
        settings.LLM_MONTHLY_MAX_REQUESTS = 10
        async with factory() as session:
            profile = await CandidateProfileRepository(session).get_primary_profile()
            from backend.tests.phase2a_fakes import PROJECT
            await CandidateProfileRepository(session).update_primary_profile(CandidateProfileUpdate(projects=[PROJECT]), profile.version)
            await session.commit()
            service = ApplicationAnswerService(session, settings, FakeProvider(), manager)
            result = await service.generate(GenerateRequest(question="Describe a project", save_draft=True))
            assert result.status == "draft_ready", result
            await session.rollback()
        assert await connection.fetchval("SELECT count(*) FROM job_agent.application_answer_drafts") == 1
        assert await connection.fetchval("SELECT requests FROM job_agent.llm_monthly_usage") == 1
        assert await connection.fetchval("SELECT input_tokens FROM job_agent.llm_monthly_usage") == 120
        # Migration replay preserves every record and profile version, including new data.
        snapshots = {table: await connection.fetchval(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM job_agent.{table} t")
                     for table in ["candidate_profiles", "candidate_resources", "candidate_evidence", "application_answer_drafts", "llm_monthly_usage"]}
        await connection.execute(migration)
        for table, snapshot in snapshots.items():
            assert await connection.fetchval(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text FROM job_agent.{table} t") == snapshot
        assert await connection.fetchval("SELECT value FROM public.phase2a_sentinel") == "preserve"
        assert await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", cid) == before_company
        print("Phase 2A PostgreSQL: migration replay, existing records/versions, public sentinel, RLS, resource/evidence/draft persistence, FK, primary races, rollback, draft review/staleness, atomic quota and durable token usage: PASS")
    finally:
        if engine:
            await engine.dispose()
        if connection:
            await connection.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
