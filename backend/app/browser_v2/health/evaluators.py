"""Pure health parsers / evaluators (unit-tested offline)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.browser_v2.health.base import (
    CONNECTION_CAP,
    CONNECTION_WARN_AT,
    FAIL,
    FAILURE_SCREENSHOT_CAP,
    HEARTBEAT_STALE_AFTER,
    LEGACY_RUST_LABEL,
    OK,
    SKIP,
    WARN,
    Check,
)
from backend.app.browser_v2.logrotate import MAX_BYTES

# --- pure parsers / evaluators (unit-tested) -------------------------------------------------
_HOLDER = re.compile(r"^\s*pid (\d+)\(([^)]*)\):\s*\[[^\]]*\]\s*\S+\s+(\w+)\s+named:\s*\"([^\"]*)\"")


def parse_pmset_assertions(text: str) -> dict[str, Any]:
    """System-wide PreventUserIdleSystemSleep count + the processes holding it."""
    system: dict[str, int] = {}
    holders: list[dict[str, Any]] = []
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Assertion status system-wide"):
            section = "system"
            continue
        if stripped.startswith("Listed by owning process"):
            section = "owners"
            continue
        if section == "system":
            parts = stripped.split()
            if len(parts) == 2 and parts[1].isdigit():
                system[parts[0]] = int(parts[1])
        elif section == "owners":
            match = _HOLDER.match(line)
            if match:
                holders.append({"pid": int(match.group(1)), "process": match.group(2), "type": match.group(3),
                                "name": match.group(4)[:120]})
            behalf = _ON_BEHALF.search(line)
            if behalf and holders:  # "caffeinate asserting on behalf of '<python>' (pid N)"
                holders[-1]["on_behalf_of"] = int(behalf.group(1))
    idle = [h for h in holders if h["type"] == "PreventUserIdleSystemSleep"]
    return {"prevent_user_idle_system_sleep": system.get("PreventUserIdleSystemSleep", 0),
            "caffeinate_pids": sorted({h["pid"] for h in idle if h["process"] == "caffeinate"}),
            "caffeinate_on_behalf_of": sorted({h["on_behalf_of"] for h in idle if h["process"] == "caffeinate"
                                               and h.get("on_behalf_of")}),
            "holders": idle}


# Live 2026-11-27: launchd's worker-v2 pid is the python child; caffeinate reports it here.
_ON_BEHALF = re.compile(r"asserting on behalf of .*\(pid (\d+)\)")


def parse_launchctl_list(text: str) -> dict[str, dict[str, Any]]:
    """`launchctl list` rows -> {label: {pid, last_exit}} (pid None when not running)."""
    rows: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "PID":
            continue
        pid_text, status_text, label = (p.strip() for p in parts)
        rows[label] = {"pid": int(pid_text) if pid_text.lstrip("-").isdigit() and pid_text != "-" else None,
                       "last_exit": int(status_text) if status_text.lstrip("-").isdigit() else None}
    return rows


def evaluate_sleep(assertions: Mapping[str, Any], services: Mapping[str, Mapping[str, Any]]) -> Check:
    worker = services.get("com.automated-apply.worker-v2")
    count = int(assertions.get("prevent_user_idle_system_sleep") or 0)
    caffeinate = list(assertions.get("caffeinate_pids") or [])
    data = {"prevent_user_idle_system_sleep": count, "caffeinate_pids": caffeinate,
            "worker_v2_loaded": worker is not None, "worker_v2_pid": (worker or {}).get("pid")}
    if worker is None:
        return Check("sleep_prevention", WARN, "worker-v2 is not loaded under launchd (caffeinate -i inactive); "
                     "run backend/scripts/cutover_v2.py apply", data)
    owners = set(caffeinate) | set(assertions.get("caffeinate_on_behalf_of") or [])
    if worker.get("pid") and worker["pid"] in owners:
        return Check("sleep_prevention", OK, "worker-v2 holds PreventUserIdleSystemSleep via caffeinate -i", data)
    if count and caffeinate:
        return Check("sleep_prevention", WARN, "a caffeinate assertion is active but not owned by worker-v2", data)
    return Check("sleep_prevention", WARN, "worker-v2 is loaded but no caffeinate PreventUserIdleSystemSleep "
                 "assertion is active (the Mac may idle-sleep while locked)", data)


def evaluate_connections(count: int | None) -> Check:
    """`count` excludes this health check's own connection."""
    if count is None:
        return Check("db_connections", SKIP, "connection count unavailable", {})
    data = {"other_connections": count, "cap": CONNECTION_CAP, "warn_at": CONNECTION_WARN_AT}
    if count >= CONNECTION_CAP:
        return Check("db_connections", FAIL, f"{count} other connections for the runtime role: at the "
                     f"{CONNECTION_CAP}-connection Supabase cap", data)
    if count >= CONNECTION_WARN_AT:
        return Check("db_connections", WARN, f"{count} other connections (>= {CONNECTION_WARN_AT}); only this "
                     "probe's spare slot remains. Stop stray CLI/MCP sessions.", data)
    return Check("db_connections", OK, f"{count} other connections (budget: API <= 3 + worker 1 + 1 spare)", data)


def evaluate_heartbeat(heartbeat_at: datetime | None, desired: str | None, observed: str | None,
                       now: datetime | None = None) -> Check:
    now = now or datetime.now(UTC)
    data: dict[str, Any] = {"desired_state": desired, "observed_state": observed,
                            "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None}
    if heartbeat_at is None:
        return Check("worker_heartbeat", WARN, "worker has never reported a heartbeat", data)
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    age = now - heartbeat_at
    data["age_sec"] = int(age.total_seconds())
    if age <= HEARTBEAT_STALE_AFTER:
        return Check("worker_heartbeat", OK, f"heartbeat {int(age.total_seconds())}s ago ({observed})", data)
    status = FAIL if desired == "RUNNING" else WARN
    return Check("worker_heartbeat", status, f"stale heartbeat: {int(age.total_seconds() // 60)} min old "
                 f"(desired={desired}, observed={observed})", data)


def evaluate_telegram(polling_state: str | None, services: Mapping[str, Any]) -> Check:
    rust_loaded = LEGACY_RUST_LABEL in services
    data = {"polling_state": polling_state, "legacy_rust_loaded": rust_loaded}
    if rust_loaded:
        return Check("telegram_conflict", FAIL, f"{LEGACY_RUST_LABEL} is still loaded: it polls the same bot "
                     "token (HTTP 409). Retire it with cutover_v2.py apply.", data)
    if polling_state == "conflict":
        return Check("telegram_conflict", FAIL, "telegram_v2_state reports a 409 conflict (another poller)", data)
    if polling_state in {None, "unconfigured"}:
        return Check("telegram_conflict", WARN, f"Telegram poller state: {polling_state or 'unknown'}", data)
    return Check("telegram_conflict", OK, f"Telegram poller state: {polling_state}; no legacy Rust poller", data)


def evaluate_failure_screenshots(count: int) -> Check:
    data = {"count": count, "cap": FAILURE_SCREENSHOT_CAP}
    if count > FAILURE_SCREENSHOT_CAP:
        return Check("failure_screenshots", WARN, f"{count} failure screenshots (> {FAILURE_SCREENSHOT_CAP}); "
                     "pruning has not run", data)
    return Check("failure_screenshots", OK, f"{count} failure screenshots (<= {FAILURE_SCREENSHOT_CAP})", data)


def evaluate_logs(sizes: Mapping[str, int], max_bytes: int = MAX_BYTES) -> Check:
    big = {name: size for name, size in sizes.items() if size > max_bytes}
    data = {"sizes": dict(sizes), "max_bytes": max_bytes}
    if big:
        return Check("log_sizes", WARN, f"{len(big)} log(s) over {max_bytes // (1024 * 1024)} MB "
                     "(rotated at next service start / hourly in the worker)", data)
    return Check("log_sizes", OK, f"{len(sizes)} log file(s), all <= {max_bytes // (1024 * 1024)} MB", data)


def parse_brave_rss(ps_text: str, profile_path: Path) -> dict[str, Any]:
    needle = f"--user-data-dir={profile_path}"
    pids, rss_kb = [], 0
    for line in ps_text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and needle in parts[2]:
            pids.append(int(parts[0]))
            rss_kb += int(parts[1])
    return {"processes": len(pids), "rss_mb": round(rss_kb / 1024, 1)}


def summarize(checks: Iterable[Check]) -> dict[str, Any]:
    items = list(checks)
    statuses = {c.status for c in items}
    overall = FAIL if FAIL in statuses else WARN if WARN in statuses else OK
    return {"status": overall, "ok": overall != FAIL,
            "counts": {s: sum(c.status == s for c in items) for s in (OK, WARN, FAIL, SKIP)},
            "checks": [asdict(c) for c in items]}
