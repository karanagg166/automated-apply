"""Inspect explicitly selected configuration; no database or provider connections."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.operations.configuration import OperationRejected, load_settings
from backend.app.operations.readiness import environment_readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    try:
        report = environment_readiness(load_settings(args.env_file))
        print(report.model_dump_json(indent=2))
        return 2 if report.status == "needs_configuration" else 0
    except OperationRejected as exc:
        print(
            json.dumps(
                {
                    "status": "needs_configuration",
                    "error": str(exc),
                    "production_ready": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
