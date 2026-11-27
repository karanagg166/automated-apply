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
    "email_drafts", "worker_control", "telegram_v2_state", "mail_events",
})
# Phase 9 (followup 005): a second all-or-none group that requires the 004 core.
PHASE9_MIGRATION = ROOT / "supabase/fresh_public/followups/005_python_v2_phase9.sql"
# Additive followups applied with `migrate_v2_core apply-followup <name>` (after 004 + 005).
FOLLOWUP_MIGRATIONS = {
    "006": ROOT / "supabase/fresh_public/followups/006_semantic_cache_v2.sql",
    "007": ROOT / "supabase/fresh_public/followups/007_telegram_notifications.sql",
}
PHASE9_TABLES = frozenset({
    "watcher_state", "agent_audit_log", "agent_conversation_turns", "profile_sync_runs",
})
# Columns 005 adds to 004 tables (recognised automatically: 004 tables overlay all actual columns).
PHASE9_COLUMNS = {
    "applications": ("priority", "posted_at", "posted_precision", "priority_reason", "discovered_via"),
    "portal_rules": ("circuit_failures", "circuit_level", "circuit_open_until", "circuit_reason",
                     "last_fresh_sweep_at"),
}
# Followup 007 (zero-spam Telegram): a third all-or-none group that requires 004 + 005.
NOTIFY_TABLES = frozenset({"telegram_notification_ledger", "telegram_digest_queue"})
ALL_TABLES = TABLES | PHASE9_TABLES | NOTIFY_TABLES
APPEND_ONLY = frozenset({"application_state_events", "agent_audit_log"})
KEYED_SECTIONS = ("tables", "columns", "constraints", "triggers", "policies", "service_grants")


def installed_tables(actual_tables):
    present = TABLES.intersection(actual_tables)
    if present and present != TABLES:
        raise RuntimeError("python_v2_schema_partial_install")
    phase9 = PHASE9_TABLES.intersection(actual_tables)
    if phase9 and (phase9 != PHASE9_TABLES or not present):
        raise RuntimeError("python_v2_phase9_schema_partial_install")
    notify = NOTIFY_TABLES.intersection(actual_tables)
    if notify and (notify != NOTIFY_TABLES or not phase9):
        raise RuntimeError("python_v2_followup007_schema_partial_install")
    return present | phase9 | notify


def phase9_installed(actual_tables) -> bool:
    return bool(PHASE9_TABLES.intersection(installed_tables(actual_tables)))


def _belongs(section, key, definition):
    if section == "indexes":
        return isinstance(definition, str) and any(
            f" ON public.{name} " in definition for name in ALL_TABLES)
    if section == "tables":
        return key in ALL_TABLES
    return key.split(".", 1)[0] in ALL_TABLES


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
