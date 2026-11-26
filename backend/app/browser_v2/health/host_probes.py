"""Read-only live host probes: subprocess/HTTP runners, Brave, AI/mail, disk, Telegram, launchd."""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.health.base import (
    FAIL,
    OK,
    V2_LABELS,
    WARN,
    Check,
    Fetcher,
    Runner,
)
from backend.app.browser_v2.health.evaluators import (
    evaluate_failure_screenshots,
    evaluate_logs,
    parse_brave_rss,
)
from backend.app.browser_v2.logrotate import log_dir


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
