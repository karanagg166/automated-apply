"""Freeze actual professional research DTOs without settings, provider clients or database."""
import argparse
import json
import runpy
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator

ROOT=Path(__file__).resolve().parents[2]
load=runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def models():
    scope={"__name__":__name__,"BaseModel":BaseModel,"ConfigDict":ConfigDict,"EmailStr":EmailStr,
           "Field":Field,"StringConstraints":StringConstraints,"Annotated":Annotated,"Literal":Literal,
           "field_validator":field_validator,"model_validator":model_validator,"datetime":datetime,
           "PublicHTTPSURL":runpy.run_path(str(ROOT / "backend/app/core/urls.py"))["PublicHTTPSURL"],
           "canonical_job_url":runpy.run_path(str(ROOT / "backend/app/core/job_urls.py"))["canonical_job_url"]}
    load(scope,"backend/app/schemas/discovery.py",{"Text"})
    load(scope,"backend/app/services/people_discovery/base.py",{"Role","PublicPerson","OfficialPersonEvidence","PeopleQuery"})
    return {"public-person":scope["PublicPerson"],"official-person-evidence":scope["OfficialPersonEvidence"],"people-query":scope["PeopleQuery"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write",action="store_true")
    modes.add_argument("--check",action="store_true")
    args=parser.parse_args()
    for name,model in models().items():
        path=ROOT / "rust/agent-runtime/schemas" / (name+".json")
        content=json.dumps(model.model_json_schema(),sort_keys=True,indent=2)+"\n"
        if args.write:path.write_text(content)
        elif not path.is_file() or path.read_text()!=content:raise SystemExit("people_contract_schema_drift")


if __name__=="__main__":main()
