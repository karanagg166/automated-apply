"""Phase 9 health-check items (pure evaluators)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.browser_v2.health import FAIL, OK, WARN, db_checks
from backend.app.browser_v2.health.phase9_checks import (
    evaluate_circuits,
    evaluate_migration_005,
    evaluate_priority_queue,
    evaluate_profile_sync,
    evaluate_watchers,
    phase9_checks,
)
from backend.app.operations.v2_schema import PHASE9_COLUMNS, PHASE9_TABLES

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
ALL_TABLES = dict.fromkeys(PHASE9_TABLES, True)
ALL_COLUMNS = {t: list(c) for t, c in PHASE9_COLUMNS.items()}


def test_migration_005_ok_and_missing() -> None:
    assert evaluate_migration_005(ALL_TABLES, ALL_COLUMNS).status == OK
    missing = evaluate_migration_005({**ALL_TABLES, "agent_audit_log": False}, {"applications": []})
    assert missing.status == FAIL and "apply-phase9" in missing.detail
    assert "agent_audit_log" in missing.data["missing_tables"] and "priority" in missing.data["missing_columns"][
        "applications"]


def test_circuits_watchers_queue_profile_sync() -> None:
    assert evaluate_circuits([], NOW).status == OK
    rows = [{"platform": "naukri", "circuit_level": 2, "circuit_open_until": NOW + timedelta(minutes=5)},
            {"platform": "instahyre", "circuit_level": 1, "circuit_open_until": NOW - timedelta(minutes=1)}]
    check = evaluate_circuits(rows, NOW)
    assert check.status == WARN and check.data["open"] == ["naukri"]
    assert evaluate_watchers([], NOW).status == WARN
    blocked = evaluate_watchers([{"source": "greenhouse:acme", "open_until": NOW + timedelta(minutes=9)},
                                 {"source": "wwr:rss", "open_until": None}], NOW)
    assert blocked.status == WARN and blocked.data["blocked"] == ["greenhouse:acme"]
    assert evaluate_watchers([{"source": "wwr:rss", "open_until": None}], NOW).status == OK
    assert "P0=2" in evaluate_priority_queue({0: 2, 2: 7}).detail
    assert evaluate_profile_sync([]).status == OK
    assert evaluate_profile_sync([{"platform": "naukri", "status": "failed", "dry_run": True}]).status == WARN


def test_phase9_checks_hook_into_db_checks() -> None:
    snapshot = {"tables": {}, "other_connections": 0, "phase9_tables": ALL_TABLES, "phase9_columns": ALL_COLUMNS,
                "circuits": [], "watchers": [{"source": "wwr:rss", "open_until": None}],
                "priority_queue": {1: 3}, "profile_sync": []}
    names = [c.name for c in db_checks(snapshot, now=NOW)]
    for name in ("migration_005", "portal_circuits", "fast_poll_watchers", "priority_queue", "profile_sync"):
        assert name in names
    assert phase9_checks({"tables": {}}) == []  # pre-005 snapshot: no Phase 9 items
