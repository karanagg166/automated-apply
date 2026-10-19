"""Inspect a selected staging configuration for both services without any network access."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.operations.configuration import OperationRejected, load_settings
from backend.app.operations.workspace import FrontendSettings, workspace_readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    try:
        report = workspace_readiness(
            load_settings(args.env_file), FrontendSettings(_env_file=args.env_file)
        )
        print(json.dumps(report, indent=2))
        return 2 if report["status"] == "needs_configuration" else 0
    except ValidationError:
        print(json.dumps({"status": "needs_configuration", "error": "invalid_frontend_configuration_values_redacted"}))
        return 2
    except OperationRejected as exc:
        print(json.dumps({"status": "needs_configuration", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
