"""Read-only runtime connectivity and migration compatibility evidence. Never DDL."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import configure_operator
from backend.app.db.safety import database_target, local_target
from backend.app.db.session import close_db_engine, get_engine
from backend.app.operations.configuration import load_settings, target_identity


async def run(env_file):
    settings = load_settings(env_file)
    target = database_target(settings)
    if settings.ENVIRONMENT == "testing":
        raise ValueError("runtime_database_check_requires_non_test_configuration")
    configure_operator(settings)
    # ORM metadata must be imported after choosing the explicit operator config.
    from backend.app.operations.health import database_health

    try:
        evidence = await database_health(get_engine(), settings)
        return {**evidence, "actual_connection_verified": True,
                "remote_postgresql_verified": not local_target(target.host),
                "target_id": target_identity(settings), "ddl_executed": False}
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args.env_file))))
    except Exception:
        print(json.dumps({"actual_connection_verified": False, "ddl_executed": False,
                          "error": "database_configuration_connection_or_schema_incompatible"}))
        raise SystemExit(2) from None
