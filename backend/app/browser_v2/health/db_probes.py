"""Read-only DB snapshot (one short-lived connection) and the checks derived from it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from backend.app.browser_v2.health.base import FAIL, OK, V2_TABLES, WARN, Check
from backend.app.browser_v2.health.evaluators import (
    evaluate_connections,
    evaluate_heartbeat,
)
from backend.app.browser_v2.health.phase9_checks import phase9_checks, phase9_snapshot


async def db_snapshot(settings: Any) -> dict[str, Any]:
    """One short-lived connection, SELECT only."""
    import asyncpg

    from backend.app.db.safety import database_connect_args

    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url, **database_connect_args(settings))
    try:
        present = await connection.fetch(
            "SELECT t AS name, to_regclass('public.' || t) IS NOT NULL AS present FROM unnest($1::text[]) AS t",
            list(V2_TABLES))
        tables = {r["name"]: bool(r["present"]) for r in present}
        others = await connection.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE usename = current_user AND pid <> pg_backend_pid()")
        snapshot: dict[str, Any] = {"tables": tables, "other_connections": int(others)}
        if tables.get("worker_control"):
            row = await connection.fetchrow(
                "SELECT desired_state, observed_state, heartbeat_at, dry_run FROM public.worker_control "
                "WHERE singleton_key='primary'")
            snapshot["worker"] = dict(row) if row else None
        if tables.get("telegram_v2_state"):
            snapshot["telegram_state"] = await connection.fetchval(
                "SELECT polling_state FROM public.telegram_v2_state WHERE singleton_key='primary'")
        if tables.get("applications"):  # Phase 8: never-replay fences migrated by 004
            snapshot["never_replay"] = {r["reason"]: int(r["n"]) for r in await connection.fetch(
                "SELECT reason, count(*) AS n FROM public.applications "
                "WHERE state IN ('APPLIED','SUBMISSION_UNKNOWN') AND reason LIKE 'migrated_%never_replay' "
                "GROUP BY reason")}
            snapshot["never_replay_total"] = int(await connection.fetchval(
                "SELECT count(*) FROM public.applications WHERE state IN ('APPLIED','SUBMISSION_UNKNOWN')"))
        if tables.get("portal_rules"):  # Phase 8: per-portal session readiness
            snapshot["portals"] = [dict(r) for r in await connection.fetch(
                "SELECT platform, enabled, auto_apply_enabled, auth_status, auth_checked_at "
                "FROM public.portal_rules ORDER BY platform")]
        if tables.get("applications"):  # Phase 9: migration 005 + breakers, watchers, queue, profile sync
            snapshot |= await phase9_snapshot(connection)
        return snapshot
    finally:
        await connection.close()


def db_checks(snapshot: Mapping[str, Any] | None, error: str | None = None,
              now: datetime | None = None) -> list[Check]:
    if snapshot is None:
        return [Check("database", FAIL, f"database unreachable: {error or 'unknown'}", {})]
    tables = snapshot.get("tables") or {}
    missing = sorted(name for name, present in tables.items() if not present)
    checks = [Check("migration_004", OK if not missing else FAIL,
                    f"all {len(V2_TABLES)} v2 tables present" if not missing else f"missing v2 tables: {', '.join(missing)} "
                    "(run migrate_v2_core check -> apply)", {"missing": missing})]
    checks.append(evaluate_connections(snapshot.get("other_connections")))
    worker = snapshot.get("worker")
    if worker is not None:
        checks.append(evaluate_heartbeat(worker.get("heartbeat_at"), worker.get("desired_state"),
                                         worker.get("observed_state"), now))
    if "never_replay" in snapshot:
        checks.append(evaluate_fences(snapshot.get("never_replay") or {}, snapshot.get("never_replay_total")))
    if "portals" in snapshot:
        checks.append(evaluate_portal_sessions(snapshot.get("portals") or []))
    if worker is not None and "portals" in snapshot:
        checks.append(evaluate_live_mode(worker.get("dry_run"), snapshot.get("portals") or []))
    checks.extend(phase9_checks(snapshot, now))
    return checks


def evaluate_live_mode(dry_run: Any, portals: Iterable[Mapping[str, Any]]) -> Check:
    """Go-live gate: a 24/7 worker with dry_run=true or no auto-apply portal never clicks Apply."""
    auto = [p["platform"] for p in portals if p.get("enabled") and p.get("auto_apply_enabled")]
    data = {"dry_run": bool(dry_run), "auto_apply_portals": auto}
    if dry_run is None or dry_run:
        return Check("live_mode", WARN, "worker_control.dry_run=true: the worker inspects and scores but never "
                     "clicks Apply (switch to LIVE in /autopilot after the apply-one canary)", data)
    if not auto:
        return Check("live_mode", WARN, "auto-apply is off on every enabled portal: the worker only inspects "
                     "and scores (enable auto-apply per portal in /autopilot)", data)
    return Check("live_mode", OK, f"LIVE: auto-apply on {', '.join(auto)}", data)


def evaluate_fences(fences: Mapping[str, int], total: int | None) -> Check:
    """Never-replay rows (APPLIED / SUBMISSION_UNKNOWN) incl. the fences migrated by 004."""
    migrated = sum(fences.values())
    return Check("never_replay_fences", OK if migrated else WARN,
                 f"{migrated} migrated never-replay fence(s); {total or 0} APPLIED/SUBMISSION_UNKNOWN row(s) "
                 "are never re-applied" if migrated else "no migrated never-replay fences found (re-run "
                 "migrate_v2_core check)", {"migrated": dict(fences), "never_replay_total": total})


def evaluate_portal_sessions(portals: Iterable[Mapping[str, Any]]) -> Check:
    """Enabled browser portals must have auth_status OK before going live."""
    from backend.app.browser_v2.portals import PORTALS

    rows = list(portals)
    enabled = [p for p in rows if p.get("enabled")]
    needs_login = [p["platform"] for p in enabled
                   if PORTALS.get(p["platform"]) is not None and PORTALS[p["platform"]].requires_login
                   and p.get("auth_status") != "OK"]
    data = {"enabled": [p["platform"] for p in enabled],
            "auto_apply": [p["platform"] for p in enabled if p.get("auto_apply_enabled")],
            "auth": {p["platform"]: p.get("auth_status") for p in rows},
            "login_needed": needs_login}
    if not enabled:
        return Check("portal_sessions", WARN, "no portal is enabled in portal_rules", data)
    if needs_login:
        return Check("portal_sessions", WARN, f"enabled portal(s) not logged in: {', '.join(needs_login)} "
                     "(run cli login-setup --portal <name>, then /resume <name>)", data)
    return Check("portal_sessions", OK, f"{len(enabled)} enabled portal(s) ready", data)
