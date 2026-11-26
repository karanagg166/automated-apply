"""Health-check orchestration (`run_health`) and the text renderer."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from backend.app.browser_v2.health.base import (
    API_HEALTH_URL,
    DASHBOARD_URL,
    FAIL,
    LEGACY_RUST_LABEL,
    OK,
    SKIP,
    V2_LABELS,
    WARN,
    Check,
    Fetcher,
    Runner,
)
from backend.app.browser_v2.health.db_probes import db_checks, db_snapshot
from backend.app.browser_v2.health.evaluators import (
    evaluate_sleep,
    evaluate_telegram,
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
