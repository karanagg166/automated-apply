"""Explicit isolated fictional FastAPI fixture for the Chrome stack smoke."""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    from backend.app.core.config import Settings, configure_operator
    from backend.app.operations.configuration import load_settings

    settings = load_settings(args.env_file)
    if settings.ENVIRONMENT != "testing":
        raise SystemExit("fictional_fixture_required")
    postgres = settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    if postgres:
        target = urlsplit(settings.DATABASE_URL)
        if (target.hostname != "127.0.0.1" or (target.port or 0) <= 1024
                or target.port in {5432, 54322}
                or target.path != "/candidate_profile_test" or target.username != "postgres"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", target.password or "")
                or target.query or target.fragment
                or settings.DATABASE_SCHEMA != "job_agent"):
            raise SystemExit("disposable_loopback_postgresql_required")
    else:
        if not settings.DATABASE_URL.startswith("sqlite+aiosqlite:////"):
            raise SystemExit("fictional_sqlite_fixture_required")
        database = Path(settings.DATABASE_URL.removeprefix("sqlite+aiosqlite:///"))
        if database.exists() or database.parent != Path(args.env_file).parent:
            raise SystemExit("fresh_same_directory_fixture_required")
    configure_operator(Settings(**settings.model_dump(), _env_file=None))
    from backend.app.main import app

    async def seed():
        from sqlalchemy import text

        from backend.app.db.session import (
            close_db_engine,
            get_engine,
            get_session_factory,
        )
        from backend.app.local_agent.profile_confirmation import confirm_profile
        from backend.app.models.application_answer import CandidateResource
        from backend.app.models.base import Base
        from backend.app.repositories.candidate_profile import (
            CandidateProfileRepository,
        )
        from backend.app.schemas.candidate_profile import CandidateProfileCreate

        async with get_engine().begin() as connection:
            if postgres:
                if await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='job_agent')")):
                    raise SystemExit("fresh_database_required")
                await connection.execute(text("CREATE SCHEMA job_agent"))
            await connection.run_sync(Base.metadata.create_all)
        async with get_session_factory()() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name="Alex Example", email="alex@example.com", phone="+1-202-555-0100",
                verified_experience_years=2, verified_skills=["Python"],
            ))
            await confirm_profile(session, profile, profile.version)
            session.add(CandidateResource(candidate_profile_id=profile.id, resource_type="resume",
                label="Fictional confirmed resume", url="https://fictional.example/resume.pdf",
                user_confirmed=True, is_primary=True))
            await session.commit()
        await close_db_engine()

    asyncio.run(seed())
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off", log_level="error", access_log=False)


if __name__ == "__main__":
    main()
