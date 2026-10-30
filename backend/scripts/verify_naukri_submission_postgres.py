"""One committed fictional native/worker/receipt journey on fresh loopback PG.

Never reads the owner's environment, online database, browser, resume or tokens.
The caller creates a new disposable database; existing schemas are refused.
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def verify(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or not re.fullmatch(r"/candidate_profile_test_submission(?:_[a-z0-9]+)?", parsed.path) or parsed.port in {None, 5432, 54322}
            or parsed.query or parsed.username != "postgres" or parsed.password):
        raise ValueError("fresh_disposable_loopback_postgresql_required")
    from cryptography.fernet import Fernet
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.config import Settings, configure_operator

    key = Fernet.generate_key()
    fixture_url = url.replace("postgresql://postgres@", "postgresql+asyncpg://postgres:fictional_fixture_only@", 1)
    config = Settings(_env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="job_agent",
                      DATABASE_URL=fixture_url,
                      RESUME_ENCRYPTION_KEY=key.decode(), COHERE_ENABLED=False, GEMINI_ENABLED=False, OLLAMA_ENABLED=False,
                      GMAIL_LOCAL_ACCOUNTS_ENABLED=False, GMAIL_SENDING_ENABLED=False)
    configure_operator(config)
    from backend.app.dashboard.models import OwnerPreference, PrivateResume
    from backend.app.execution import application_queue as queue
    from backend.app.execution import profile_sync
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.main import app  # noqa: F401 -- register full ORM schema
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.base import Base
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.tests.test_naukri_submission import (
        test_complete_native_worker_direct_apply_and_two_independent_receipts,
    )

    started = perf_counter()
    engine = create_async_engine(config.DATABASE_URL, hide_parameters=True, pool_size=2, max_overflow=0,
                                 connect_args={"server_settings": {"search_path": "job_agent,public"}})
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    import backend.app.db.session as session_module

    session_module._engine, session_module._session_factory = engine, factory
    try:
        async with engine.begin() as connection:
            if await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')")):
                raise ValueError("fresh_database_required")
            await connection.execute(text("CREATE SCHEMA job_agent"))
            await connection.run_sync(Base.metadata.create_all)
            version = await connection.scalar(text("SHOW server_version"))
        raw = b"%PDF-1.4\nFictional PostgreSQL submission journey only\n%%EOF"
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name="Alex Fictional", email="alex@example.com", verified_experience_years=2,
                verified_skills=["Python"], summary="Verified fictional summary",
                preferences={"target_titles": ["Backend Developer"], "preferred_locations": ["India"]},
            ))
            resource = CandidateResource(id=uuid4(), candidate_profile_id=profile.id, resource_type="resume",
                                         label="Fictional canonical PDF", source_type="private_upload",
                                         user_confirmed=True, is_primary=True, url="private-resume:pending")
            session.add(resource)
            await session.flush()
            private = PrivateResume(id=uuid4(), label="Fictional canonical PDF", resource_id=resource.id,
                                    confirmed=True, ciphertext=Fernet(key).encrypt(raw), sha256=hashlib.sha256(raw).hexdigest())
            session.add(private)
            resource.url = "private-resume:" + str(private.id)
            await confirm_profile(session, profile, profile.version)
            await session.commit()
            case = SimpleNamespace(key=key, private=private, settings=config, raw=raw)
            await test_complete_native_worker_direct_apply_and_two_independent_receipts(session, case)
        # Verify persisted results using a new connection/session after the full
        # production dispatcher and worker transactions committed independently.
        async with factory() as reader:
            result = await queue.listing(reader, stage="SUBMITTED_CONFIRMED")
            assert result["total"] == 1
            record_key = profile_sync.RECORD + str(uuid4())
            assert len(record_key) <= 50
            await queue.put(reader, record_key, {"decisions": profile_sync.compare({"summary": "verified"}, {"summary": "old"}, ["summary"])})
            await reader.commit()
        async with factory() as reader:
            assert await reader.get(OwnerPreference, record_key)
        print(json.dumps({"fixture_only": True, "database_version": version, "cases_passed": 2,
                          "duration_seconds": round(perf_counter() - started, 3), "pool_limit": 2,
                          "provider_requests": 0, "real_applications": 0,
                          "results": ["committed_native_worker_apply_and_independent_receipt_journey", "profile_sync_reference_record_survives_new_connection"]}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    asyncio.run(verify(parser.parse_args().url))
