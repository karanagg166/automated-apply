"""Phase 9 health items: migration 005, persisted portal circuit breakers, fast-poll watchers,
the early-bird priority queue and portal profile sync. Read-only SQL on the health snapshot's
single short-lived connection; pure evaluators below."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from backend.app.browser_v2.health.base import FAIL, OK, WARN, Check
from backend.app.operations.v2_schema import PHASE9_COLUMNS, PHASE9_TABLES


async def phase9_snapshot(connection: Any) -> dict[str, Any]:
    present = await connection.fetch(
        "SELECT t AS name, to_regclass('public.' || t) IS NOT NULL AS present FROM unnest($1::text[]) AS t",
        sorted(PHASE9_TABLES))
    tables = {r["name"]: bool(r["present"]) for r in present}
    columns: dict[str, list[str]] = {}
    for table, wanted in PHASE9_COLUMNS.items():
        rows = await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=$1 AND column_name=ANY($2::text[])", table, list(wanted))
        columns[table] = sorted(r["column_name"] for r in rows)
    snapshot: dict[str, Any] = {"phase9_tables": tables, "phase9_columns": columns}
    complete = all(tables.values()) and all(set(columns.get(t, [])) == set(c) for t, c in PHASE9_COLUMNS.items())
    if not complete:
        return snapshot
    snapshot["circuits"] = [dict(r) for r in await connection.fetch(
        "SELECT platform, enabled, circuit_level, circuit_open_until, circuit_reason "
        "FROM public.portal_rules WHERE circuit_open_until IS NOT NULL OR circuit_level > 0 ORDER BY platform")]
    snapshot["watchers"] = [dict(r) for r in await connection.fetch(
        "SELECT source, failures, open_until, last_poll_at, last_error FROM public.watcher_state "
        "WHERE source NOT LIKE '%:budget' ORDER BY source")]
    snapshot["priority_queue"] = {int(r["priority"]): int(r["n"]) for r in await connection.fetch(
        "SELECT priority, count(*) AS n FROM public.applications "
        "WHERE state IN ('DISCOVERED','SCORED') GROUP BY priority")}
    snapshot["profile_sync"] = [dict(r) for r in await connection.fetch(
        "SELECT DISTINCT ON (platform) platform, status, dry_run, started_at FROM public.profile_sync_runs "
        "ORDER BY platform, started_at DESC")]
    return snapshot


def evaluate_migration_005(tables: Mapping[str, bool], columns: Mapping[str, Iterable[str]]) -> Check:
    missing_tables = sorted(name for name, ok in tables.items() if not ok)
    missing_columns = {t: sorted(set(c) - set(columns.get(t, []))) for t, c in PHASE9_COLUMNS.items()}
    missing_columns = {t: c for t, c in missing_columns.items() if c}
    data = {"missing_tables": missing_tables, "missing_columns": missing_columns}
    if not missing_tables and not missing_columns:
        return Check("migration_005", OK, f"Phase 9 schema present ({len(PHASE9_TABLES)} tables + priority/circuit "
                     "columns)", data)
    return Check("migration_005", FAIL, "Phase 9 schema missing: run `python -m backend.scripts.migrate_v2_core "
                 "apply-phase9` (the worker refuses to start without it)", data)


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def evaluate_circuits(rows: Iterable[Mapping[str, Any]], now: datetime) -> Check:
    open_now = [r["platform"] for r in rows if (_aware(r.get("circuit_open_until")) or now) > now]
    data = {"open": open_now, "levels": {r["platform"]: r.get("circuit_level") for r in rows}}
    if open_now:
        return Check("portal_circuits", WARN, f"circuit open (cooling down) on: {', '.join(open_now)}; other "
                     "portals keep running", data)
    return Check("portal_circuits", OK, "no portal circuit breaker is open", data)


def evaluate_watchers(rows: Iterable[Mapping[str, Any]], now: datetime) -> Check:
    items = list(rows)
    blocked = [r["source"] for r in items if (_aware(r.get("open_until")) or now) > now]
    data = {"sources": len(items), "blocked": blocked}
    if not items:
        return Check("fast_poll_watchers", WARN, "no watcher has polled yet (worker not started on Phase 9 code, "
                     "or every feed portal is disabled)", data)
    if blocked:
        return Check("fast_poll_watchers", WARN, f"{len(blocked)}/{len(items)} watcher source(s) backing off: "
                     f"{', '.join(blocked[:5])}", data)
    return Check("fast_poll_watchers", OK, f"{len(items)} watcher source(s) healthy", data)


def evaluate_priority_queue(counts: Mapping[int, int]) -> Check:
    label = ", ".join(f"P{tier}={counts.get(tier, 0)}" for tier in range(4))
    return Check("priority_queue", OK, f"pending jobs by tier: {label}", {f"P{k}": v for k, v in counts.items()})


def evaluate_profile_sync(rows: Iterable[Mapping[str, Any]]) -> Check:
    items = list(rows)
    data = {r["platform"]: {"status": r.get("status"), "dry_run": r.get("dry_run")} for r in items}
    failed = [r["platform"] for r in items if r.get("status") == "failed"]
    if failed:
        return Check("profile_sync", WARN, f"last profile sync failed on: {', '.join(failed)}", data)
    if not items:
        return Check("profile_sync", OK, "no profile sync run yet (portals are dry-run / uncalibrated by default)",
                     data)
    return Check("profile_sync", OK, f"{len(items)} portal(s) have profile-sync history", data)


def phase9_checks(snapshot: Mapping[str, Any], now: datetime | None = None) -> list[Check]:
    if "phase9_tables" not in snapshot:
        return []
    moment = now or datetime.now(UTC)
    checks = [evaluate_migration_005(snapshot.get("phase9_tables") or {}, snapshot.get("phase9_columns") or {})]
    if "circuits" in snapshot:
        checks.append(evaluate_circuits(snapshot.get("circuits") or [], moment))
        checks.append(evaluate_watchers(snapshot.get("watchers") or [], moment))
        checks.append(evaluate_priority_queue(snapshot.get("priority_queue") or {}))
        checks.append(evaluate_profile_sync(snapshot.get("profile_sync") or []))
    return checks
