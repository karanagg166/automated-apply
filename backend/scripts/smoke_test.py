"""Offline fixture exercise, staging SELECT-only inspection, or explicitly authorized live pilot."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import configure_operator
from backend.app.operations.configuration import (
    OperationRejected,
    load_settings,
    require_staging,
)
from backend.app.operations.reports import execution_metadata, write_report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["local-offline", "staging-read-only", "explicit-live-pilot"],
        default="local-offline",
    )
    parser.add_argument("--env-file")
    parser.add_argument("--confirm-staging-target")
    parser.add_argument("--approve-profile-inspection", action="store_true")
    parser.add_argument("--output", default="reports")
    parser.add_argument("pilot_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.mode == "explicit-live-pilot":
        from backend.scripts.run_startup_pilot import arguments, execute

        remainder = args.pilot_arguments
        return await execute(
            arguments(remainder[1:] if remainder[:1] == ["--"] else remainder)
        )
    if args.mode == "local-offline":
        from backend.app.operations.offline import offline_demo

        report = {
            **execution_metadata(args.mode, "testing_disposable_SQLite"),
            **await offline_demo(),
        }
        code = 0
    else:
        settings = load_settings(args.env_file)
        require_staging(settings, args.confirm_staging_target)
        configure_operator(settings)
        from sqlalchemy import text

        from backend.app.db.session import close_db_engine, get_session_factory
        from backend.app.operations.diagnostics import operational_status
        from backend.app.operations.migrations import inspect_database
        from backend.app.operations.network import NetworkAudit
        from backend.app.operations.readiness import environment_readiness
        from backend.app.services.startup_discovery.connectivity import (
            ProviderConnectivity,
        )

        with NetworkAudit() as network:
            migration = await inspect_database(settings)
            report = {
                **execution_metadata(args.mode, "staging"),
                "migration": migration.model_dump(),
            }
            code = 0 if migration.status == "verified" else 2
            if code == 0:
                try:
                    factory = get_session_factory()
                    async with factory() as session:
                        await session.execute(text("SET TRANSACTION READ ONLY"))
                        if args.approve_profile_inspection:
                            report["operations"] = await operational_status(
                                session, factory, settings
                            )
                        else:
                            report["configuration"] = environment_readiness(
                                settings
                            ).model_dump()
                            report["providers"] = await ProviderConnectivity(
                                session, factory, settings
                            ).status()
                            report["profile"] = (
                                "not_inspected_owner_permission_required"
                            )
                        await session.rollback()
                finally:
                    await close_db_engine()
            report.update(network.output(), emails_sent=0, applications_submitted=0)
    write_report(args.output, report)
    print(json.dumps(report, indent=2, default=str))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(json.dumps({"status": "failed", "error": "smoke_failed_values_redacted"}))
        raise SystemExit(3)
