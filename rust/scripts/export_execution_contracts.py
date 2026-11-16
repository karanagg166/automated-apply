"""Freeze legacy execution DTOs without importing application settings or services."""

import argparse
import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
NAMES = {
    "QueuePolicy": "application-queue-policy",
    "QueuePolicyUpdate": "application-queue-policy-update",
    "QueueControl": "application-queue-control",
    "Configuration": "execution-configuration",
    "Control": "execution-control",
    "Start": "execution-start",
    "AccountApproval": "naukri-account-approval",
    "SyncPolicy": "naukri-profile-sync-policy",
    "SyncPolicyUpdate": "naukri-profile-sync-policy-update",
}


def load(scope, source, names):
    body = []
    for node in ast.parse((ROOT / source).read_text()).body:
        name = (
            node.name
            if isinstance(node, ast.ClassDef)
            else (
                node.targets[0].id
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                else None
            )
        )
        if name in names:
            body.append(node)
    if len(body) != len(names):
        raise ValueError("execution_contract_source_requires_review")
    exec(compile(ast.Module(body=body, type_ignores=[]), source, "exec"), scope)


def render():
    scope = {
        "__name__": __name__,
        "BaseModel": BaseModel,
        "ConfigDict": ConfigDict,
        "Field": Field,
        "field_validator": field_validator,
        "model_validator": model_validator,
        "Literal": Literal,
        "UUID": UUID,
        "date": date,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "ZoneInfo": ZoneInfo,
        "ZoneInfoNotFoundError": ZoneInfoNotFoundError,
    }
    load(
        scope,
        "backend/app/execution/contracts.py",
        {"Contract", "Mode", "State", "Configuration", "Control", "Start"},
    )
    load(
        scope,
        "backend/app/execution/queue_contracts.py",
        {
            "Platform",
            "Stage",
            "QueueLimits",
            "QueuePreferences",
            "PlatformQueuePolicy",
            "QueuePolicy",
            "QueuePolicyUpdate",
            "QueueControl",
        },
    )
    load(scope, "backend/app/execution/naukri_identity.py", {"AccountApproval"})
    load(
        scope,
        "backend/app/execution/profile_sync.py",
        {"FieldName", "SyncPolicy", "SyncPolicyUpdate"},
    )
    return {
        name: json.dumps(scope[kind].model_json_schema(), indent=2, sort_keys=True)
        + "\n"
        for kind, name in NAMES.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    for name, content in render().items():
        path = ROOT / "rust/agent-runtime/schemas" / (name + ".json")
        if arguments.write:
            path.write_text(content)
        elif not path.is_file() or path.read_text() != content:
            raise SystemExit("execution_contract_schema_drift")


if __name__ == "__main__":
    main()
