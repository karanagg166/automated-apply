"""Bounded explicit free public diagnostic; durable staging pacing, never paid providers."""

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


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--confirm-staging-target", required=True)
    parser.add_argument("--authorize-public-check", action="store_true")
    parser.add_argument(
        "--source",
        choices=["hacker_news", "arbeitnow", "remotive", "greenhouse"],
        required=True,
    )
    args = parser.parse_args()
    settings = load_settings(args.env_file)
    require_staging(settings, args.confirm_staging_target)
    if not args.authorize_public_check:
        raise OperationRejected("explicit_free_source_check_authorization_required")
    configure_operator(settings)
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.operations.migrations import inspect_database
    from backend.app.operations.network import PUBLIC_HOSTS, NetworkAudit
    from backend.app.services.startup_discovery.connectivity import ProviderConnectivity

    if (await inspect_database(settings)).status != "verified":
        raise OperationRejected("migration_preflight_required")
    try:
        with NetworkAudit(PUBLIC_HOSTS) as network:
            factory = get_session_factory()
            async with factory() as session:
                result = await ProviderConnectivity(session, factory, settings).check(
                    args.source
                )
        print(
            json.dumps(
                {"environment": "staging", "check": result, **network.output()},
                indent=2,
            )
        )
        return 0 if result["state"] == "live_verified" else 2
    finally:
        await close_db_engine()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "provider_check_unavailable_values_redacted",
                }
            )
        )
        raise SystemExit(3)
