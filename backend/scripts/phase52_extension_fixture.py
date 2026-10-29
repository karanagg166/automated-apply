"""Explicit isolated fictional FastAPI/SQLite fixture for the Chrome stack smoke."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    from backend.app.core.config import Settings, configure_operator
    from backend.app.operations.configuration import load_settings

    settings = load_settings(args.env_file)
    if settings.ENVIRONMENT != "testing" or not settings.DATABASE_URL.startswith("sqlite+aiosqlite:////"):
        raise SystemExit("fictional_sqlite_fixture_required")
    database = Path(settings.DATABASE_URL.removeprefix("sqlite+aiosqlite:///"))
    if database.exists() or database.parent != Path(args.env_file).parent:
        raise SystemExit("fresh_same_directory_fixture_required")
    configure_operator(Settings(**settings.model_dump(), _env_file=None))
    from backend.app.main import app

    async def seed():
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
