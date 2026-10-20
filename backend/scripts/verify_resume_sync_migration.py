"""Disposable-localhost PostgreSQL: migration, races, approval and crash recovery."""

import asyncio
import hashlib
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
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.path != "/candidate_profile_test" or parsed.query or parsed.fragment:
        raise ValueError("Only disposable localhost candidate_profile_test is permitted")
    admin = await asyncpg.connect(url)
    database = "candidate_profile_test_resume_" + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    child_url = urlunsplit(parsed._replace(path="/" + database))
    connection, engine = None, None
    try:
        connection = await asyncpg.connect(child_url)
        for role in ("anon", "authenticated", "service_role"):
            if not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
                await connection.execute(f'CREATE ROLE "{role}" NOLOGIN' + (" BYPASSRLS" if role == "service_role" else ""))
        paths = sorted((ROOT / "supabase/migrations").glob("*.sql"))
        for path in paths[:-1]:
            await connection.execute(path.read_text())
        await connection.execute("CREATE TABLE public.resume_preservation_probe(value text)")
        await connection.execute("INSERT INTO public.resume_preservation_probe VALUES ('unchanged')")
        await connection.execute("INSERT INTO job_agent.candidate_profiles(full_name,email,verified_skills) VALUES ('Alex Fictional','alex@example.org','[\"Python\",\"FastAPI\"]')")
        profile_id = await connection.fetchval("SELECT id FROM job_agent.candidate_profiles")
        await connection.execute(paths[-1].read_text())
        assert await connection.fetchval("SELECT value FROM public.resume_preservation_probe") == "unchanged"
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles WHERE id=$1", profile_id) == 1
        for table in ("resume_drive_sources", "drive_resume_versions", "resume_profile_reviews"):
            assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass", "job_agent." + table)
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated',$1,'SELECT')", "job_agent." + table)
            assert await connection.fetchval("SELECT has_table_privilege('service_role',$1,'SELECT,INSERT,UPDATE,DELETE')", "job_agent." + table)
        await connection.execute("SET ROLE anon")
        try:
            await connection.fetch("SELECT * FROM job_agent.private_resumes LIMIT 1")
        except asyncpg.InsufficientPrivilegeError:
            pass
        else:
            raise AssertionError("Browser client role must not read private resumes")
        finally:
            await connection.execute("RESET ROLE")

        from cryptography.fernet import Fernet
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.core.config import Settings, configure_operator

        settings = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_URL=child_url.replace("postgresql://", "postgresql+asyncpg://"),
                            CANDIDATE_RESUME_DRIVE_URL="https://drive.google.com/file/d/fictional_drive_resume_001/view",
                            CANDIDATE_RESUME_DRIVE_FILE_ID="fictional_drive_resume_001", RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode())
        configure_operator(settings)
        from backend.app.dashboard.models import (
            Notification,
            OwnerPreference,
            PrivateResume,
        )
        from backend.app.models.candidate_profile import CandidateProfile
        from backend.app.resume_sync.download import DownloadedPDF
        from backend.app.resume_sync.models import (
            DriveResumeVersion,
            ResumeProfileReview,
        )
        from backend.app.resume_sync.review import approve_version, review_changes
        from backend.app.resume_sync.schemas import ApproveResume
        from backend.app.resume_sync.service import ResumeSyncService
        from backend.app.resume_sync.store import status
        from backend.tests.test_phase7_dashboard import pdf_bytes

        engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            session.add(OwnerPreference(key="notifications", value={"quiet_start": 0, "quiet_end": 0}))
        raw = pdf_bytes("Alex Fictional Python Docker")
        extractions = []
        async def download(_):
            await asyncio.sleep(0.05)
            return DownloadedPDF(raw, "fictional_resume.pdf")
        async def extract(_):
            extractions.append(True)
            return {"text": "Alex Fictional\nPython Docker"}
        async def sync():
            async with factory() as session, session.begin():
                return await ResumeSyncService(session, settings, download, extract).sync(1)
        results = await asyncio.gather(sync(), sync())
        assert {result["outcome"] for result in results} == {"pending_review", "unchanged"}
        assert len(extractions) == 1
        first_id = results[0]["state"].latest.id
        async with factory() as session, session.begin():
            for model in (PrivateResume, DriveResumeVersion, ResumeProfileReview, Notification):
                assert await session.scalar(select(func.count()).select_from(model)) == 1
        # Recreate the pool, as after an API process restart. Pending state and
        # encrypted bytes must survive independently of a session/engine cache.
        await engine.dispose()
        engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            saved = await session.scalar(select(PrivateResume))
            decrypted = Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()).decrypt(saved.ciphertext)
            assert decrypted == raw and hashlib.sha256(decrypted).hexdigest() == saved.sha256
            assert (await status(session, settings)).pending_changes
            assert await session.scalar(select(CandidateProfile.version)) == 1
        from backend.app.operations.health import database_health

        evidence = await database_health(engine, settings.model_copy(update={
            "ENVIRONMENT": "development", "DB_REMOTE_ONLY": False, "DB_REQUIRE_TLS": False,
        }))
        assert evidence["migration_011"] == "catalog_compatible_history_untracked"
        assert evidence["schema"] == "job_agent"
        async def approve(version_id):
            async with factory() as session, session.begin():
                review = await review_changes(session, settings, version_id)
                return await approve_version(session, settings, version_id, ApproveResume(
                    owner_confirmed=True, expected_generation=1, expected_profile_version=review.expected_profile_version,
                    profile=review.current_profile, primary=True,
                ))
        await asyncio.gather(approve(first_id), approve(first_id))
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles WHERE id=$1", profile_id) == 2
        raw = pdf_bytes("Alex Fictional Python Redis")
        async with factory() as session:
            service = ResumeSyncService(session, settings, download, extract)
            async def interrupted(_):
                raise asyncio.CancelledError
            service.notify = interrupted
            try:
                async with session.begin():
                    await service.sync(1)
            except asyncio.CancelledError:
                pass
        async with factory() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(DriveResumeVersion)) == 1
        await asyncio.gather(sync(), sync())
        async with factory() as session, session.begin():
            state = await status(session, settings)
            assert len(state.history) == 2 and state.active.id == first_id
            second_id = state.latest.id
            assert await session.scalar(select(CandidateProfile.version)) == 2
        accepted = await approve(second_id)
        assert accepted.active.id == second_id and accepted.latest.approved_profile_version == 3
        assert await connection.fetchval("SELECT version FROM job_agent.candidate_profiles WHERE id=$1", profile_id) == 3
        assert await connection.fetchval("SELECT count(*) FROM job_agent.private_resumes") == 2
        print("Resume sync PostgreSQL PASS: migration 011; RLS/grants; concurrent deduplication; resume-only version advances; prior bytes preserved; interrupted transaction recovery")
    finally:
        if engine:
            await engine.dispose()
        if connection:
            await connection.close()
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", database)
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"]))
