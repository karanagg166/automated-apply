"""Freeze actual reviewed actor configuration without importing provider clients/settings."""
import argparse
import json
import runpy
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ROOT=Path(__file__).resolve().parents[2]
load=runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def model():
    scope={"__name__":__name__,"BaseModel":BaseModel,"ConfigDict":ConfigDict,"Field":Field,
           "StringConstraints":StringConstraints,"Annotated":Annotated,"Any":Any,"Literal":Literal,
           "datetime":datetime,"PublicHTTPSURL":runpy.run_path(str(ROOT / "backend/app/core/urls.py"))["PublicHTTPSURL"]}
    load(scope,"backend/app/services/job_sources/apify_adapter.py",{"ActorConfiguration"})
    return scope["ActorConfiguration"]


def metadata_models():
    scope={"__name__":__name__,"BaseModel":BaseModel,"ConfigDict":ConfigDict,"Field":Field,
           "Any":Any,"Literal":Literal,"datetime":datetime}
    load(scope,"backend/app/services/providers/apify.py",{"ActorMetadata"})
    load(scope,"backend/app/ai/schemas.py",{"Contract"})
    load(scope,"backend/app/api/v1/provider_research.py",{"ActorInspect"})
    return {"actor-metadata":scope["ActorMetadata"],"actor-inspect":scope["ActorInspect"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write",action="store_true")
    modes.add_argument("--check",action="store_true")
    args=parser.parse_args()
    for name,contract in {"actor-configuration":model(),**metadata_models()}.items():
        path=ROOT / f"rust/agent-runtime/schemas/apify-{name}.json"
        content=json.dumps(contract.model_json_schema(),sort_keys=True,indent=2)+"\n"
        if args.write:path.write_text(content)
        elif not path.is_file() or path.read_text()!=content:raise SystemExit("apify_contract_schema_drift")


if __name__=="__main__":main()
