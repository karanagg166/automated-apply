"""Read-only recognition of the Python v2 core tables (followup 004). No DDL.

The legacy public verifier pins every catalog object. The v2 tables are
recognised all-or-none; their ACL contract is still enforced by
verify_restricted_runtime (owner, forced RLS, exact runtime privileges).
"""

from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "supabase/fresh_public/followups/004_python_v2_core_tables.sql"
TABLES = frozenset({
    "portal_rules", "applications", "application_state_events", "hitl_requests",
    "semantic_cache", "llm_provider_usage", "enrichment_cache", "enrichment_credits",
    "email_drafts", "worker_control", "telegram_v2_state",
})
APPEND_ONLY = frozenset({"application_state_events"})
KEYED_SECTIONS = ("tables", "columns", "constraints", "triggers", "policies", "service_grants")


def installed_tables(actual_tables):
    present = TABLES.intersection(actual_tables)
    if present and present != TABLES:
        raise RuntimeError("python_v2_schema_partial_install")
    return present


def _belongs(section, key, definition):
    if section == "indexes":
        return isinstance(definition, str) and any(
            f" ON public.{name} " in definition for name in TABLES)
    if section == "tables":
        return key in TABLES
    return key.split(".", 1)[0] in TABLES


def expected_overlay(expected, actual):
    """Add the installed v2 objects to the pinned expectation, refusing collisions."""
    if not installed_tables(actual.get("tables", {})):
        return expected
    result = deepcopy(expected)
    for section in (*KEYED_SECTIONS, "indexes"):
        records = {key: value for key, value in actual.get(section, {}).items()
                   if _belongs(section, key, value)}
        if set(result.get(section, {})).intersection(records):
            raise RuntimeError("python_v2_schema_namespace_collision")
        result.setdefault(section, {}).update(records)
    return result
