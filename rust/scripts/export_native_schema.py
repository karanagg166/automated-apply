"""Export public contracts only; never load settings, env files or candidate records."""
import argparse
import json
from pathlib import Path

from backend.app.local_agent.contracts import Command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "native-host/schemas/command.json"
    content = json.dumps(Command.model_json_schema(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if target.read_text() != content:
            raise SystemExit("native_schema_drift")
        print("native_schema_current")
    else:
        target.write_text(content)


if __name__ == "__main__":
    main()
