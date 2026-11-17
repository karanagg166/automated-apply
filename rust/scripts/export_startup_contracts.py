"""Freeze actual saved startup query/shortlist DTOs without application settings/services."""
import argparse
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
load = runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def models():
    scope = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
             "Field": Field, "StringConstraints": StringConstraints, "Annotated": Annotated,
             "Literal": Literal, "field_validator": field_validator, "model_validator": model_validator,
             "UUID": UUID, "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
             "PublicHTTPSURL":runpy.run_path(str(ROOT / "backend/app/core/urls.py"))["PublicHTTPSURL"],
             "NormalizedJob":runpy.run_path(str(ROOT / "backend/app/schemas/normalized_job.py"))["NormalizedJob"]}
    load(scope, "backend/app/schemas/discovery.py", {"Text", "DiscoveryQuery"})
    load(scope, "backend/app/services/startup_discovery/schemas.py", {"Band", "Hiring", "Key", "CompanyObservation", "StartupFilters", "StartupRunRequest", "ShortlistInput", "StartupAttributes", "HiringEvidence", "SizeEvidence", "StartupRead", "StartupSearchRead"})
    return {"startup-filters": scope["StartupFilters"], "startup-shortlist": scope["ShortlistInput"],
            "startup-read": scope["StartupRead"], "startup-search": scope["StartupSearchRead"],
            "company-observation":scope["CompanyObservation"],"startup-run-request":scope["StartupRunRequest"],
            "normalized-job":scope["NormalizedJob"],"discovery-query":scope["DiscoveryQuery"]}


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
