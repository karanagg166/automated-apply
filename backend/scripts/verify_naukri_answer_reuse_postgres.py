"""Verify answer-bank storage on fresh loopback PostgreSQL, never owner data."""

import argparse
import asyncio
import json
import re
from time import perf_counter
from urllib.parse import urlsplit


async def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname != "127.0.0.1"
        or parsed.port in {None, 5432, 54322}
        or not re.fullmatch(r"/candidate_profile_test_answer_reuse_[a-z0-9]+", parsed.path)
        or parsed.username != "postgres"
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("fresh_disposable_loopback_postgresql_required")

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.config import Settings, configure_operator

    configure_operator(Settings(
        _env_file=None, ENVIRONMENT="testing", DATABASE_SCHEMA="job_agent",
        DATABASE_URL=url.replace("postgresql://", "postgresql+asyncpg://", 1),
        COHERE_ENABLED=False, GEMINI_ENABLED=False, OLLAMA_ENABLED=False,
        GMAIL_LOCAL_ACCOUNTS_ENABLED=False, GMAIL_SENDING_ENABLED=False,
    ))
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.execution import application_queue as queue
    from backend.app.execution.naukri_questionnaires import reuse_key
    from backend.app.models.base import Base

    started = perf_counter()
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=1, max_overflow=0, hide_parameters=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    results = []
    try:
        async with engine.begin() as connection:
            assert not await connection.scalar(text(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')"
            )), "fresh_database_required"
            await connection.execute(text("CREATE SCHEMA job_agent"))
            await connection.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[OwnerPreference.__table__]
            ))
            version = await connection.scalar(text("SHOW server_version"))
            maximum = await connection.scalar(text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_schema='job_agent' AND table_name='owner_preferences' "
                "AND column_name='key'"
            ))
            assert maximum == 50
        # Real PostgreSQL rejects the old encoding; SQLite does not enforce it.
        async with factory() as session, session.begin():
            try:
                async with session.begin_nested():
                    session.add(OwnerPreference(
                        key="apply_answer_bank:" + "a" * 64, value={"fixture": True}
                    ))
                    await session.flush()
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "22001"
            else:
                raise AssertionError("oversized_key_was_not_rejected")
            results.append("old_key_rejected_by_real_varchar50")
            value = {"candidate_profile_id": "fictional-profile", "profile_version": 1,
                     "facts": {"company": "Fictional Example", "description": "Fixture"}}
            step = {"question": "Why do you want to join this company?",
                    "answer_kind": "text", "options": []}
            key = reuse_key(value, step)
            assert len(key) == maximum
            await queue.put(session, key, {
                "fixture": True, "answer": "Fictional example only",
                "question_id": "fictional-question", "profile_version": 1,
            })
            results.append("new_full_hash_key_commits_with_unchanged_schema")
        async with factory() as session:
            row = await session.get(OwnerPreference, key)
            assert row.value["answer"] == "Fictional example only"
            assert await session.get(OwnerPreference, reuse_key(
                {**value, "profile_version": 2}, step
            )) is None
            results.append("fresh_session_recovers_only_matching_profile_scope")
        print(json.dumps({"fixture_only": True, "postgresql": version,
                          "groups": results, "count": len(results),
                          "duration_seconds": round(perf_counter() - started, 3),
                          "live_provider_requests": 0, "owner_database_access": False}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    asyncio.run(verify(parser.parse_args().database_url))
