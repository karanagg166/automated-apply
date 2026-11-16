"""Freeze actual outreach DTOs without loading settings, mail or provider services."""
import argparse
import json
import runpy
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
load = runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def models():
    scope = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
             "EmailStr": EmailStr, "Field": Field, "field_validator": field_validator,
             "model_validator": model_validator, "Literal": Literal, "UUID": UUID}
    load(scope, "backend/app/schemas/outreach.py", {"DraftInput", "DraftEdit", "DraftDecision"})
    return {"outreach-input": scope["DraftInput"], "outreach-edit": scope["DraftEdit"], "outreach-decision": scope["DraftDecision"]}


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
            raise SystemExit("outreach_contract_schema_drift")


if __name__ == "__main__":
    main()
