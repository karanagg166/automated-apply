"""Non-destructive 24/7 watchdog health check (Phase 6B).

    backend/venv/bin/python -m backend.app.browser_v2.cli health-check [--json] [--no-db]

Every probe is read-only: `pmset -g assertions`, `launchctl list`, HTTP GETs to the local
API/dashboard, SELECT-only queries on one short-lived DB connection (the spare slot in the
Supabase 5-connection budget), `ps` for Brave RSS, and file stats. Nothing is started,
stopped, inserted or sent. Parsers are pure functions so they are unit-tested offline.
"""

from __future__ import annotations

from backend.app.browser_v2.health.base import (
    API_HEALTH_URL,
    CONNECTION_CAP,
    CONNECTION_WARN_AT,
    DASHBOARD_URL,
    FAIL,
    FAILURE_SCREENSHOT_CAP,
    HEARTBEAT_STALE_AFTER,
    LEGACY_RUST_LABEL,
    OK,
    SKIP,
    V2_LABELS,
    V2_TABLES,
    WARN,
    Check,
    Fetcher,
    Runner,
)
from backend.app.browser_v2.health.db_probes import (
    db_checks,
    db_snapshot,
    evaluate_fences,
    evaluate_live_mode,
    evaluate_portal_sessions,
)
from backend.app.browser_v2.health.evaluators import (
    _HOLDER,
    _ON_BEHALF,
    evaluate_connections,
    evaluate_failure_screenshots,
    evaluate_heartbeat,
    evaluate_logs,
    evaluate_sleep,
    evaluate_telegram,
    parse_brave_rss,
    parse_launchctl_list,
    parse_pmset_assertions,
    summarize,
)
from backend.app.browser_v2.health.host_probes import (
    check_ai_and_mail,
    check_brave,
    check_disk,
    check_http,
    check_launchd_plists,
    check_telegram_config,
    default_fetch,
    default_runner,
)
from backend.app.browser_v2.health.runner import render_text, run_health

__all__ = [
    "API_HEALTH_URL",
    "CONNECTION_CAP",
    "CONNECTION_WARN_AT",
    "DASHBOARD_URL",
    "FAIL",
    "FAILURE_SCREENSHOT_CAP",
    "HEARTBEAT_STALE_AFTER",
    "LEGACY_RUST_LABEL",
    "OK",
    "SKIP",
    "V2_LABELS",
    "V2_TABLES",
    "WARN",
    "_HOLDER",
    "_ON_BEHALF",
    "Check",
    "Fetcher",
    "Runner",
    "check_ai_and_mail",
    "check_brave",
    "check_disk",
    "check_http",
    "check_launchd_plists",
    "check_telegram_config",
    "db_checks",
    "db_snapshot",
    "default_fetch",
    "default_runner",
    "evaluate_connections",
    "evaluate_failure_screenshots",
    "evaluate_fences",
    "evaluate_heartbeat",
    "evaluate_live_mode",
    "evaluate_logs",
    "evaluate_portal_sessions",
    "evaluate_sleep",
    "evaluate_telegram",
    "parse_brave_rss",
    "parse_launchctl_list",
    "parse_pmset_assertions",
    "render_text",
    "run_health",
    "summarize",
]
