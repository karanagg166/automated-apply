"""Freeze actual Gmail DTO declarations without importing configuration or mail services."""
import argparse
import json
import re
import runpy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, model_validator

ROOT = Path(__file__).resolve().parents[2]
load = runpy.run_path(str(ROOT / "rust/scripts/export_execution_contracts.py"))["load"]


def models():
    scope = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
             "Field": Field, "StrictBool": StrictBool, "model_validator": model_validator,
             "datetime": datetime, "timezone": timezone, "UUID": UUID, "re": re,
             "EmailStr": EmailStr, "Literal": Literal,
             "PublicHTTPSURL": runpy.run_path(str(ROOT / "backend/app/core/urls.py"))["PublicHTTPSURL"]}
    load(scope, "backend/app/ai/schemas.py", {"Contract"})
    load(scope, "backend/app/integrations/gmail/history.py", {"HistoryReview"})
    load(scope, "backend/app/integrations/gmail/workspace.py", {"Version", "Retention"})
    load(scope, "backend/app/integrations/gmail/read_service.py", {"ReadConnect", "ReadPolicy", "LeadImport"})
    return {"gmail-history-review": scope["HistoryReview"], "gmail-history-version": scope["Version"],
            "gmail-history-retention": scope["Retention"], "gmail-read-connect": scope["ReadConnect"],
            "gmail-read-policy": scope["ReadPolicy"], "gmail-lead-import": scope["LeadImport"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, model in models().items():
        path = ROOT / "rust/agent-runtime/schemas" / (name + ".json")
        content = json.dumps(model.model_json_schema(), sort_keys=True, indent=2) + "\n"
        if args.write:
            path.write_text(content)
        elif not path.is_file() or path.read_text() != content:
            raise SystemExit("gmail_contract_schema_drift")


if __name__ == "__main__":
    main()
