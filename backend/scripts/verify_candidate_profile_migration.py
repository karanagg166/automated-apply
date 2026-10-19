"""Executable integration assertions against a disposable local database.

Requires PROFILE_TEST_DATABASE_URL with localhost and database candidate_profile_test.
Creates/drops only its own unique candidate_profile_test_* database, never a shared DB.
"""
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
    database = "candidate_profile_test_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    isolated_url = urlunsplit(parsed._replace(path="/" + database))
    engine = None
    connection = None
    try:
        # Override settings before importing models; no .env credentials are used.
        os.environ["DATABASE_URL"] = isolated_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        os.environ["DATABASE_SCHEMA"] = "job_agent"
        os.environ["ENVIRONMENT"] = "testing"
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from backend.app.models.job import Job
        from backend.app.repositories.candidate_profile import CandidateProfileRepository, ProfileConflictError
        from backend.app.schemas.candidate_profile import CandidateProfileCreate, CandidateProfileUpdate
        from backend.app.services.candidate_profile_service import CandidateProfileService
        from backend.app.services.application_assistant import ApplicationAssistant
        from backend.app.repositories.job import JobRepository
        connection = await asyncpg.connect(isolated_url)
        await connection.execute((ROOT / "supabase/migrations/001_initial_schema.sql").read_text())
        # Sentinel belongs only to this disposable test database.
        await connection.execute("CREATE TABLE public.migration_sentinel (value text); INSERT INTO public.migration_sentinel VALUES ('preserve')")
        company_id = await connection.fetchval("INSERT INTO job_agent.companies (name) VALUES ('Existing Example') RETURNING id")
        before = await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", company_id)
        public_before = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        migration = (ROOT / "supabase/migrations/002_candidate_profile.sql").read_text()
        await connection.execute(migration)
        await connection.execute(migration)  # Retry-safe DDL.
        assert await connection.fetchval("SELECT value FROM public.migration_sentinel") == "preserve"
        assert await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename") == public_before
        assert await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", company_id) == before
        assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='job_agent.candidate_profiles'::regclass") is True
        assert await connection.fetchval("SELECT count(*) FROM pg_policies WHERE schemaname='job_agent' AND tablename='candidate_profiles'") == 0
        # Current Job ORM requires the additive discovery columns.
        await connection.execute((ROOT / "supabase/migrations/004_job_discovery.sql").read_text())
        engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        payload = CandidateProfileCreate(full_name="Alex Example", email="alex@example.com", verified_skills=["Python"], preferences={"remote_preference": "remote"})

        async def create():
            async with factory() as session:
                try:
                    profile = await CandidateProfileRepository(session).create_primary_profile(payload)
                    await session.commit()
                    return profile.id
                except ProfileConflictError:
                    await session.rollback()
                    return "conflict"
        created = await asyncio.gather(create(), create())
        assert created.count("conflict") == 1
        assert await connection.fetchval("SELECT count(*) FROM job_agent.candidate_profiles") == 1

        async def update(summary):
            async with factory() as session:
                try:
                    result = await CandidateProfileRepository(session).update_primary_profile(CandidateProfileUpdate(summary=summary), 1)
                    await session.commit()
                    return result.version
                except ProfileConflictError:
                    await session.rollback()
                    return "conflict"
        assert sorted(await asyncio.gather(update("First"), update("Second")), key=str) == [2, "conflict"]
        async with factory() as session:
            repo = CandidateProfileRepository(session)
            profile = await repo.get_primary_profile()
            assert profile.version == 2 and profile.verified_experience_years is None
            original_created = profile.created_at
            original_updated = profile.updated_at
            same, was_created = await repo.upsert_primary_profile(CandidateProfileCreate.model_validate(profile), 2)
            assert not was_created and same.version == 2 and same.updated_at == original_updated
            await repo.update_primary_profile(CandidateProfileUpdate(preferences={"preferred_locations": ["London"]}), 2)
            await session.commit()
            assert profile.version == 3 and profile.created_at == original_created
            assert profile.preferences["remote_preference"] == "remote"
            job = Job(title="Engineer", job_url="https://example.com/test-job", source_platform="manual", skills_required=["Python", "Go"], is_remote=True)
            session.add(job)
            await session.commit()
            job_id = job.id
        async with factory() as session:
            job = await JobRepository(session).get_by_id(job_id)
            assistant_profile = await CandidateProfileService(session).to_application_profile()
            result = ApplicationAssistant(session).calculate_match(job, assistant_profile)
            assert result.matched_skills == ["Python"] and result.missing_skills == ["Go"]
            assert result.location_match
            await CandidateProfileRepository(session).update_primary_profile(CandidateProfileUpdate(summary="Rolled back"), 3)
            await session.rollback()
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles") == 3
        await connection.execute("UPDATE job_agent.candidate_profiles SET summary='SQL writer'")
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles") == 4
        await connection.execute(migration)
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles") == 4
        for assignment in ["verified_experience_years=-1", "singleton_key='other'", "preferences='{" + '"minimum_salary": -1' + "}'::jsonb", "preferences='{" + '"remote_preference": "invalid"' + "}'::jsonb"]:
            try:
                await connection.execute("UPDATE job_agent.candidate_profiles SET " + assignment)
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError(f"Constraint accepted {assignment}")
        assert await connection.fetchval("SELECT row_to_json(c)::text FROM job_agent.companies c WHERE id=$1", company_id) == before
        assert await connection.fetchval("SELECT value FROM public.migration_sentinel") == "preserve"
        print("PostgreSQL 16 migration, retry, ORM CRUD, real concurrent writes, rollback, RLS, constraints, matching and existing/public record preservation: PASS")
    finally:
        if engine:
            await engine.dispose()
        if connection:
            await connection.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
