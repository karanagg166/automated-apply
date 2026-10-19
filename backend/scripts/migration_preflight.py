"""Default: offline plan. --inspect: pinned staging catalog reads; never executes DDL."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.operations.configuration import (
    OperationRejected,
    load_settings,
    require_staging,
)
from backend.app.operations.migrations import file_inventory, inspect_database


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--confirm-staging-target")
    args = parser.parse_args()
    try:
        if not args.inspect:
            output = {
                "status": "plan_only",
                "ddl_executed": False,
                "history": "untracked; inspection required",
                "migrations": file_inventory(),
            }
            code = 0
        else:
            settings = load_settings(args.env_file)
            require_staging(settings, args.confirm_staging_target)
            plan = await inspect_database(settings)
            output, code = plan.model_dump(), 0 if plan.status == "verified" else 2
        print(json.dumps(output, indent=2))
        return code
    except OperationRejected as exc:
        print(
            json.dumps({"status": "rejected", "error": str(exc), "ddl_executed": False})
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "status": "inspection_failed",
                    "error": "database_or_manifest_unavailable",
                    "ddl_executed": False,
                }
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
