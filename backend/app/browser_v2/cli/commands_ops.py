"""Ops commands: live-smoke, worker, health-check, set-portal-cred, agent-chat."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.app.browser_v2.cli.common import emit


async def live_smoke_command(checks: list[str], mail_app: bool, llm_ping: bool, portal: str) -> int:
    from backend.app.browser_v2.live_smoke import run_live_smoke

    report = await run_live_smoke(checks, mail_app=mail_app, llm_ping=llm_ping, portal=portal)
    emit(report)
    return 0 if report["ok"] else 1


async def run_worker_command(dry_run: bool, once: bool, telegram: bool = True) -> int:
    import logging

    from backend.app.browser_v2.logrotate import (
        rotate_periodically,
        rotate_service_logs,
    )
    from backend.app.browser_v2.service import plain
    from backend.app.browser_v2.worker import run_worker
    from backend.app.telegram_v2.client import install_log_redaction

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_log_redaction()  # httpx logs request URLs at INFO; the Telegram URL contains the token
    rotate_service_logs("worker-v2")  # Phase 6B: <= 10 MB x 3 backups (launchd log files)
    rotation_stop = asyncio.Event()
    rotation = asyncio.create_task(rotate_periodically("worker-v2", rotation_stop))
    try:
        reports = await run_worker(dry_run=dry_run, once=once, telegram=telegram)
    finally:
        rotation_stop.set()
        await rotation
    if once:
        emit([plain(report) for report in reports])
    return 0


def set_portal_cred_command(portal: str, vault: Any = None, *, prompt: Any = None, secret: Any = None) -> int:
    """Store a portal username + password in the macOS Keychain (service automated-apply:<portal>)."""
    import getpass

    from backend.app.browser_v2.auth import LOGIN_SPECS, KeychainVault

    if portal not in LOGIN_SPECS or not LOGIN_SPECS[portal].password_login:
        emit({"error": f"{portal} has no password login (use login-setup / Google instead)"})
        return 2
    vault = vault or KeychainVault()
    username = (prompt or input)(f"{portal} login email/username: ").strip()
    password = (secret or getpass.getpass)(f"{portal} password (hidden, stored only in macOS Keychain): ")
    if not username or not password:
        emit({"error": "username and password are required"})
        return 2
    vault.set(portal, username, password)
    emit({"stored": True, "portal": portal, "keychain_service": f"automated-apply:{portal}",
          "username": username[:2] + "•••", "note": "used only for one auto re-login per 30 min before a "
                                                    "Telegram AUTH request; never written to .env or Postgres"})
    return 0


async def agent_chat_command(text: str) -> int:
    """Run the LLM-first control agent once (same audited tools + guardrails as Telegram free chat)."""
    from backend.app.agent_v2.control_graph import ControlAgent
    from backend.app.browser_v2.service import build_ai, open_store
    from backend.app.browser_v2.store import agent_chat_key

    store, backend = await open_store(require_db=False)
    try:
        agent = ControlAgent(store, ai=await build_ai(store))
        result = await agent.run_chat(text, chat_key=agent_chat_key("cli", "owner"), source="cli")
        emit({"store": backend, **{k: v for k, v in result.items() if k != "hitl_resolutions"}})
        return 0
    finally:
        await store.close()


async def health_check_command(as_json: bool, include_db: bool) -> int:
    from backend.app.browser_v2.health import render_text, run_health

    report = await run_health(include_db=include_db)
    print(json.dumps(report, indent=2, default=str) if as_json else render_text(report))
    return 0 if report["ok"] else 1
