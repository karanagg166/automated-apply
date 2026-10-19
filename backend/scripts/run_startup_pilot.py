"""Explicit pinned-staging public pilot. Reuses services; never approves packets or sends data to AI."""

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


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--confirm-staging-target", required=True)
    parser.add_argument("--authorize-public-discovery", action="store_true")
    parser.add_argument("--approve-profile-use", action="store_true")
    parser.add_argument("--prepare-packet", action="store_true")
    parser.add_argument(
        "--source",
        choices=["hacker_news", "arbeitnow", "remotive", "greenhouse"],
        default="hacker_news",
    )
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--roles", nargs="+", default=[])
    parser.add_argument("--locations", nargs="+", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", default="reports")
    return parser.parse_args(argv)


async def execute(args):
    settings = load_settings(args.env_file)
    require_staging(settings, args.confirm_staging_target)
    if not args.authorize_public_discovery:
        raise OperationRejected("explicit_public_discovery_authorization_required")
    if settings.GMAIL_SENDING_ENABLED or settings.MCP_REMOTE_ENABLED:
        raise OperationRejected("staging_sending_and_remote_mcp_must_be_disabled")
    configure_operator(settings)
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.operations.migrations import inspect_database
    from backend.app.operations.network import PUBLIC_HOSTS, NetworkAudit
    from backend.app.operations.pilot import PilotRequest, run_pilot

    plan = await inspect_database(settings)
    if plan.status != "verified":
        raise OperationRejected("migration_preflight_required")
    try:
        factory = get_session_factory()
        async with factory() as session:
            with NetworkAudit(PUBLIC_HOSTS) as network:
                result = await run_pilot(
                    session,
                    factory,
                    settings,
                    PilotRequest(
                        source=args.source,
                        idempotency_key=args.idempotency_key,
                        use_profile=args.approve_profile_use,
                        prepare_packet=args.prepare_packet,
                        roles=args.roles,
                        locations=args.locations,
                        limit=args.limit,
                    ),
                )
            report = {
                **execution_metadata("explicit_live_pilot", "staging"),
                **result,
                **network.output(),
            }
            write_report(args.output, report)
            print(json.dumps(report, indent=2, default=str))
            return 2 if result["blockers"] else 0
    finally:
        await close_db_engine()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(execute(arguments())))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "error": "pilot_unavailable_values_redacted"}
            )
        )
        raise SystemExit(3)
