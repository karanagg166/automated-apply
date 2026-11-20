"""Export the saved review contracts without loading runtime settings."""

import argparse
import json
from pathlib import Path

from backend.app.agent.contracts import Campaign
from backend.app.browser.submission_contracts import Submission


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1] / "agent-runtime/schemas"
    for name, model in (("campaign", Campaign), ("submission", Submission)):
        path = directory / f"legacy-review-{name}.json"
        expected = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        if args.write:
            path.write_text(expected)
        elif not path.exists() or path.read_text() != expected:
            raise SystemExit(f"saved_review_{name}_contract_changed")


if __name__ == "__main__":
    main()
