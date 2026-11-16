"""Freeze actual contact correction DTOs without importing providers or settings."""
import argparse
import json
import runpy
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ROOT = Path(__file__).resolve().parents[2]
load = runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def model():
    scope = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
             "Field": Field, "StringConstraints": StringConstraints,
             "Annotated": Annotated, "Literal": Literal, "UUID": UUID}
    load(scope, "backend/app/services/contact_enrichment/schemas.py", {"Text", "ContactCorrection"})
    return scope["ContactCorrection"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "rust/agent-runtime/schemas/contact-correction.json"
    content = json.dumps(model().model_json_schema(), sort_keys=True, indent=2) + "\n"
    if args.write:
        path.write_text(content)
    elif not path.is_file() or path.read_text() != content:
        raise SystemExit("contact_contract_schema_drift")


if __name__ == "__main__":
    main()
