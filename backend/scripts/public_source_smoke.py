"""Bounded fallback when staging is unavailable: isolated SQLite, free public reads only.

One Arbeitnow sample and one HN discovery (at most 20 listings). Remotive is
excluded so this fallback cannot discard its six-hour persistent access window.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import Settings, configure_operator
from backend.app.operations.configuration import OperationRejected
from backend.app.operations.reports import execution_metadata, write_report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-public-read", action="store_true")
    parser.add_argument("--output", default="reports/public-smoke")
    args = parser.parse_args()
    if not args.authorize_public_read:
        raise OperationRejected("explicit_free_source_authorization_required")
    # A report marks an already executed attempt. Do not remove it to force replay.
    if (Path(args.output) / "phase6b-pilot-summary.json").exists():
        raise OperationRejected(
            "already_executed_use_durable_staging_pacing_for_further_runs"
        )
    with tempfile.TemporaryDirectory(prefix="phase6b-public-sqlite-") as directory:
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_SCHEMA="job_agent",
            DATABASE_URL="sqlite+aiosqlite:///" + str(Path(directory) / "public.db"),
            GEMINI_API_KEY=None,
            LLM_MODEL=None,
            GMAIL_SENDING_ENABLED=False,
            MCP_REMOTE_ENABLED=False,
            PEOPLE_SEARCH_ENABLED=False,
            SERPER_API_KEY=None,
            APIFY_API_TOKEN=None,
            APOLLO_API_KEY=None,
            SIGNALHIRE_API_KEY=None,
            GMAIL_CLIENT_ID=None,
            GMAIL_CLIENT_SECRET=None,
            LOG_LEVEL="ERROR",
        )
        configure_operator(settings)
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.app.models import Base
        from backend.app.operations.network import PUBLIC_HOSTS, NetworkAudit
        from backend.app.operations.pilot import PilotRequest, run_pilot
        from backend.app.services.startup_discovery.connectivity import (
            ProviderConnectivity,
        )

        engine = create_async_engine(settings.DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        report = execution_metadata(
            "temporary_SQLite_public_read_only", "testing_disposable_SQLite"
        )
        report.update(persistent_postgresql_verified=False, staging_deployed=False)
        # Retain an interrupted-attempt marker before network activity.
        write_report(
            args.output, {**report, "status": "started_incomplete_do_not_replay"}
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            with NetworkAudit(PUBLIC_HOSTS) as network:
                async with factory() as session:
                    diagnostic = await ProviderConnectivity(
                        session, factory, settings
                    ).check("arbeitnow")
                    result = await run_pilot(
                        session,
                        factory,
                        settings,
                        PilotRequest(idempotency_key="public_smoke_6b", limit=20),
                    )
                    status = await ProviderConnectivity(
                        session, factory, settings
                    ).status()
            report.update(
                result,
                diagnostic=diagnostic,
                provider_status=status,
                **network.output(),
            )
            write_report(args.output, report)
            print(json.dumps(report, indent=2, default=str))
            return (
                0
                if diagnostic["state"] == "live_verified"
                and result["discovery_status"] in {"success", "no_results"}
                else 2
            )
        finally:
            await engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "error": "public_smoke_failed_values_redacted"}
            )
        )
        raise SystemExit(3)
