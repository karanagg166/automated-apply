"""Authorized free discovery in durable local SQLite; no credentials or candidate data.

This is a local live-source pilot, never staging/PostgreSQL verification. Retain the
state directory: its existing source windows and idempotency records prevent replay.
"""

import argparse
import asyncio
import fcntl
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import Settings, configure_operator
from backend.app.operations.configuration import OperationRejected
from backend.app.operations.reports import execution_metadata, write_report


def public_settings(database):
    return Settings(
        _env_file=None, ENVIRONMENT="testing", UI_FIXTURE_MODE=False,
        DATABASE_URL="sqlite+aiosqlite:///" + str(database), DATABASE_SCHEMA="job_agent",
        GEMINI_API_KEY=None, LLM_MODEL=None, GMAIL_SENDING_ENABLED=False,
        GMAIL_CLIENT_ID=None, GMAIL_CLIENT_SECRET=None, GMAIL_REFRESH_TOKEN=None,
        MCP_REMOTE_ENABLED=False, PEOPLE_SEARCH_ENABLED=False,
        SERPER_API_KEY=None, APIFY_API_TOKEN=None, APOLLO_API_KEY=None,
        SIGNALHIRE_API_KEY=None, HUNTER_API_KEY=None, GREENHOUSE_BOARDS={},
        APIFY_SOURCES={}, APOLLO_ENRICHMENT_ENABLED=False,
        SIGNALHIRE_ENRICHMENT_ENABLED=False, LOG_LEVEL="ERROR",
    )


async def execute(args):
    if not args.authorize_public_read:
        raise OperationRejected("explicit_free_source_authorization_required")
    directory = Path(args.state_dir)
    if directory.is_symlink():
        raise OperationRejected("private_local_state_directory_required")
    # Configure before importing ORM models, without loading either repository .env.
    settings = public_settings(directory.resolve() / "public.sqlite")
    configure_operator(settings)
    from backend.app.operations.pilot import PilotRequest

    request = PilotRequest(source=args.source, idempotency_key=args.idempotency_key)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise OperationRejected("state_directory_must_be_private_mode_0700")
    directory = directory.resolve()
    descriptor = os.open(directory / "pilot.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperationRejected("another_local_pilot_is_running") from None
        database = directory / "public.sqlite"
        database_fd = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(database_fd, 0o600)
        os.close(database_fd)
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.models import Base
        from backend.app.operations.network import PUBLIC_HOSTS, NetworkAudit
        from backend.app.operations.pilot import run_pilot

        engine = create_async_engine(settings.DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            with NetworkAudit(PUBLIC_HOSTS) as network:
                async with factory() as session:
                    result = await run_pilot(session, factory, settings, request)
            report = {
                **execution_metadata("local_live_public_discovery", "isolated_local_SQLite"),
                **result, **network.output(), "fictional_data": False,
                "persistent_postgresql_verified": False, "staging_deployed": False,
                "owner_profile_used": False, "candidate_eligibility_verified": False,
                "paid_requests": 0,
            }
            write_report(directory / args.idempotency_key, report)
            print(json.dumps(report, indent=2, default=str))
            return 0 if result["discovery_status"] in {"success", "no_results"} else 2
        finally:
            await engine.dispose()
    finally:
        os.close(descriptor)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-public-read", action="store_true")
    parser.add_argument("--source", choices=["hacker_news", "arbeitnow", "remotive"], required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--state-dir", default="reports/phase8-public")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(execute(arguments())))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(json.dumps({"status": "failed", "error": "local_pilot_failed_values_redacted"}))
        raise SystemExit(3)
