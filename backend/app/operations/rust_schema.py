"""Exact read-only recognition of the optional Rust runtime schema. No DDL."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "supabase/runtime/001_rust_agent_runtime.review.sql"
MANIFEST = Path(__file__).with_name("rust_schema_manifest.json")
TABLES = frozenset({"rust_agent_runs", "rust_agent_events", "rust_agent_control",
                    "rust_agent_control_events", "rust_telegram_runtime", "rust_telegram_outbox"})


def installed_tables(actual_tables):
    present = TABLES.intersection(actual_tables)
    if present and present != TABLES:
        raise RuntimeError("rust_runtime_schema_partial_install")
    return present


def expected_overlay(expected, actual):
    if not installed_tables(actual.get("tables", {})):
        return expected
    manifest = json.loads(MANIFEST.read_text())
    if hashlib.sha256(PACKAGE.read_bytes()).hexdigest() != manifest["package_sha256"]:
        raise RuntimeError("rust_runtime_schema_reverification_required")
    result = deepcopy(expected)
    for section, records in manifest["catalog"].items():
        if section == "unsafe_grants":
            continue
        if set(result.get(section, {})).intersection(records):
            raise RuntimeError("rust_runtime_schema_namespace_collision")
        result.setdefault(section, {}).update(records)
    return result
