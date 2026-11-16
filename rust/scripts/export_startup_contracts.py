"""Freeze actual saved startup query/shortlist DTOs without application settings/services."""
import argparse
import json
import runpy
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ROOT = Path(__file__).resolve().parents[2]
load = runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def models():
    scope = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
             "Field": Field, "StringConstraints": StringConstraints, "Annotated": Annotated,
             "Literal": Literal, "model_validator": model_validator, "UUID": UUID, "datetime": datetime}
    load(scope, "backend/app/schemas/discovery.py", {"Text"})
    load(scope, "backend/app/services/startup_discovery/schemas.py", {"Band", "Hiring", "StartupFilters", "ShortlistInput"})
    return {"startup-filters": scope["StartupFilters"], "startup-shortlist": scope["ShortlistInput"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, model in models().items():
        path = ROOT / "rust/agent-runtime/schemas" / (name + ".json")
        content = json.dumps(model.model_json_schema(), sort_keys=True, indent=2) + "\n"
        if args.write:
            path.write_text(content)
        elif not path.is_file() or path.read_text() != content:
            raise SystemExit("startup_contract_schema_drift")


if __name__ == "__main__":
    main()
