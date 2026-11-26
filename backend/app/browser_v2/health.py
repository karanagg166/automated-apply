"""Non-destructive 24/7 watchdog health check (Phase 6B).

    backend/venv/bin/python -m backend.app.browser_v2.cli health-check [--json] [--no-db]

Every probe is read-only: `pmset -g assertions`, `launchctl list`, HTTP GETs to the local
API/dashboard, SELECT-only queries on one short-lived DB connection (the spare slot in the
Supabase 5-connection budget), `ps` for Brave RSS, and file stats. Nothing is started,
stopped, inserted or sent. Parsers are pure functions so they are unit-tested offline.
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.logrotate import MAX_BYTES, log_dir
from backend.app.operations.v2_schema import TABLES

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
API_HEALTH_URL = "http://127.0.0.1:8000/health"
DASHBOARD_URL = "http://127.0.0.1:3000/"
V2_LABELS = ("com.automated-apply.api-v2", "com.automated-apply.worker-v2", "com.automated-apply.frontend-v2")
LEGACY_RUST_LABEL = "com.automated-apply.rust"
CONNECTION_WARN_AT = 4
CONNECTION_CAP = 5
HEARTBEAT_STALE_AFTER = timedelta(minutes=5)
FAILURE_SCREENSHOT_CAP = 20
V2_TABLES = tuple(sorted(TABLES))

Runner = Callable[[list[str]], str]
Fetcher = Callable[[str], int]


@dataclass
class Check:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


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


# --- live probes ------------------------------------------------------------------------------
def default_runner(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def default_fetch(url: str) -> int:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "automated-apply-health"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def check_http(name: str, url: str, fetch: Fetcher) -> Check:
    code = fetch(url)
    if code == 0:
        return Check(name, FAIL, f"{url} unreachable", {"url": url})
    if code >= 500:
        return Check(name, FAIL, f"{url} -> HTTP {code}", {"url": url, "status": code})
    return Check(name, OK, f"{url} -> HTTP {code}", {"url": url, "status": code})


def check_brave(runner: Runner, profile_path: Path | None = None) -> Check:
    path = profile_path or brave_profile.profile_dir()
    data: dict[str, Any] = {"profile_dir": str(path), "exists": path.is_dir()}
    try:
        brave_profile.assert_allowed_location(path)
    except brave_profile.ProfileError as exc:
        return Check("brave_profile", FAIL, str(exc), data)
    if not path.is_dir():
        return Check("brave_profile", WARN, "dedicated Brave profile not created yet: run cli login-setup", data)
    lock = brave_profile.profile_lock(path)
    data |= {"lock_pid": lock.pid if lock else None, "lock_source": lock.source if lock else None,
             "exit_type": brave_profile.last_exit_type(path)}
    data |= parse_brave_rss(runner(["/bin/ps", "-axo", "pid=,rss=,args="]), path)
    if data["exit_type"] == "Crashed" and lock is None:
        return Check("brave_profile", WARN, "last Brave exit was 'Crashed' (cookies may be stale)", data)
    running = f"running, {data['processes']} proc, {data['rss_mb']} MB RSS" if data["processes"] else "not running"
    return Check("brave_profile", OK, f"profile outside ~/Desktop; Brave {running}", data)


def check_ai_and_mail(env: Mapping[str, str]) -> list[Check]:
    checks = []
    try:
        from backend.app.ai_v2.router import LLMRouter

        router = LLMRouter(env=env)
        configured = sorted(name for name, spec in router.providers.items() if spec.configured)
        status = OK if configured else WARN
        checks.append(Check("free_llm_providers", status, f"{len(configured)} free LLM provider(s) configured",
                            {"configured": configured, "count": len(configured)}))
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        checks.append(Check("free_llm_providers", WARN, f"router unavailable: {type(exc).__name__}", {}))
    try:
        from backend.app.mail_v2.config import MailConfig

        channel = MailConfig.from_env(env).active_channel()
        checks.append(Check("mail_channel", OK if channel != "unconfigured" else WARN,
                            f"draft channel={channel}; permission READ_AND_DRAFT_ONLY (sending disabled)",
                            {"channel": channel, "permission": "READ_AND_DRAFT_ONLY"}))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("mail_channel", WARN, f"mail config unavailable: {type(exc).__name__}",
                            {"permission": "READ_AND_DRAFT_ONLY"}))
    return checks


def check_disk(receipts: Path | None = None, logs: Path | None = None) -> list[Check]:
    from backend.app.browser_v2.receipts import failures_dir, receipts_root

    folder = failures_dir(receipts or receipts_root())
    count = sum(1 for p in folder.iterdir() if p.is_file()) if folder.is_dir() else 0
    base = logs or log_dir()
    sizes = {p.name: p.stat().st_size for p in sorted(base.glob("*.log"))} if base.is_dir() else {}
    return [evaluate_failure_screenshots(count), evaluate_logs(sizes)]


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


def check_telegram_config(env: Mapping[str, str]) -> Check:
    """Bot token + owner chat present and well-formed (never prints the token)."""
    from backend.app.telegram_v2.config import TelegramConfig

    config = TelegramConfig.from_env(env)
    return Check("telegram_config", OK if config.configured else WARN,
                 "bot token + owner chat configured" if config.configured
                 else f"Telegram HITL unconfigured: {config.problem}", config.public())


def check_launchd_plists(agents_dir: Path | None = None) -> Check:
    """The three v2 LaunchAgents rendered into ~/Library/LaunchAgents (cutover_v2 apply)."""
    folder = agents_dir or Path.home() / "Library" / "LaunchAgents"
    present = {label: (folder / f"{label}.plist").is_file() for label in V2_LABELS}
    missing = [label for label, ok in present.items() if not ok]
    return Check("launchd_v2_plists", OK if not missing else WARN,
                 "api-v2, worker-v2 (caffeinate -i) and frontend-v2 installed" if not missing
                 else f"not installed yet: {', '.join(m.rsplit('.', 1)[-1] for m in missing)} "
                 "(backend/scripts/cutover_v2.py apply)", {"present": present})


async def run_health(*, include_db: bool = True, runner: Runner = default_runner, fetch: Fetcher = default_fetch,
                     env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from backend.app.ai_v2.router import load_env

    env = dict(env if env is not None else load_env())
    services = {label: row for label, row in parse_launchctl_list(runner(["/bin/launchctl", "list"])).items()
                if label.startswith("com.automated-apply.")}
    checks = [evaluate_sleep(parse_pmset_assertions(runner(["/usr/bin/pmset", "-g", "assertions"])), services),
              check_http("api_v2_http", API_HEALTH_URL, fetch), check_http("dashboard_http", DASHBOARD_URL, fetch)]
    telegram_state: str | None = None
    if include_db:
        try:
            from backend.app.browser_v2.config import load_settings

            snapshot = await db_snapshot(load_settings())
            telegram_state = snapshot.get("telegram_state")
            checks.extend(db_checks(snapshot))
        except Exception as exc:  # noqa: BLE001 - report, never raise
            checks.extend(db_checks(None, f"{type(exc).__name__}"))
    else:
        checks.append(Check("database", SKIP, "skipped (--no-db)", {}))
    checks.append(check_brave(runner))
    checks.append(check_launchd_plists())
    checks.append(check_telegram_config(env))
    checks.append(evaluate_telegram(telegram_state, services))
    checks.extend(check_ai_and_mail(env))
    checks.extend(check_disk())
    report = summarize(checks)
    report["services"] = {label: services.get(label) for label in (*V2_LABELS, LEGACY_RUST_LABEL)}
    report["checked_at"] = datetime.now(UTC).isoformat()
    report["host_pid"] = os.getpid()
    return report


def render_text(report: Mapping[str, Any]) -> str:
    icons = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}
    lines = [f"automated-apply health: {report['status'].upper()}  {report['counts']}"]
    lines += [f"  [{icons[c['status']]}] {c['name']}: {c['detail']}" for c in report["checks"]]
    return "\n".join(lines)
