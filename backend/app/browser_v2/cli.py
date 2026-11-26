"""Owner CLI for the dedicated Brave profile and the Naukri adapter.

Run from the repository root:
    backend/venv/bin/python -m backend.app.browser_v2.cli login-setup
    backend/venv/bin/python -m backend.app.browser_v2.cli check-session --portal naukri --restart
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --dry-run --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --live --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run --once
    backend/venv/bin/python -m backend.app.browser_v2.cli mcp
    backend/venv/bin/python -m backend.app.browser_v2.cli ai-status [--load-embedder]
    backend/venv/bin/python -m backend.app.browser_v2.cli ai-test [--provider groq]
    backend/venv/bin/python -m backend.app.browser_v2.cli seed-cache
    backend/venv/bin/python -m backend.app.browser_v2.cli test-qa --question "..." [--option Yes --option No]
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run [--no-telegram]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-status [--probe]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-test
    backend/venv/bin/python -m backend.app.browser_v2.cli mail-status [--probe] [--mail-app] [--recent 5]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-draft --to hr@example.com --company Acme \
        --role "Backend Engineer" [--dry-run]
    backend/venv/bin/python -m backend.app.browser_v2.cli enrichment-status
    backend/venv/bin/python -m backend.app.browser_v2.cli live-smoke --check db --check mail [--mail-app]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal greenhouse --board <token> --dry-run
    backend/venv/bin/python -m backend.app.browser_v2.cli set-portal-cred --portal instahyre
    backend/venv/bin/python -m backend.app.browser_v2.cli export-sft-dataset --out ~/sft.jsonl
    backend/venv/bin/python -m backend.app.browser_v2.cli agent-chat "how many applied today?"
    backend/venv/bin/python -m backend.app.browser_v2.cli health-check [--json] [--no-db]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal instahyre --dry-run --debug-selectors

Gmail is READ + DRAFT ONLY: no command here can deliver an email.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from typing import Any

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.portals import PORTALS

PHASE1_LIVE_LIMIT = 1
MAX_INSPECTIONS_PER_APPLY = 10
MAX_DEBUG_BUNDLES = 3


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def login_setup(portals: list[str]) -> int:
    """Plain Brave (no Playwright/CDP/automation flags) so portals see a normal browser."""
    path = brave_profile.ensure_profile_dir()
    brave_profile.assert_profile_free(path)
    brave_profile.ensure_persistent_preferences(path)  # logins survive quitting/reopening Brave
    executable = brave_profile.brave_executable()
    if not executable.exists():
        emit({"error": f"Brave not found at {executable}"})
        return 2
    urls = [brave_profile.LOGIN_URLS[p] for p in portals]
    command = [str(executable), f"--user-data-dir={path}", "--no-first-run",
               "--no-default-browser-check", *urls]
    print(f"Opening plain Brave on {path}\nLog in to: {', '.join(portals)}.\n"
          "When finished, quit Brave with Cmd+Q (not just closing the window) so cookies are saved.")
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    code = process.wait()
    exit_type = brave_profile.last_exit_type(path)
    emit({"profile_dir": str(path), "brave_exit_code": code, "profile_exit_type": exit_type,
          "saved": exit_type == "Normal",
          "next": "run check-session --portal naukri --restart" if exit_type == "Normal"
          else "Brave did not exit cleanly; reopen login-setup and quit with Cmd+Q"})
    return 0 if exit_type == "Normal" else 1


async def debug_bundle(service: Any, portal: str) -> dict[str, Any]:
    """Phase 6B --debug-selectors: scrubbed DOM probe + screenshot of the current worker tab."""
    from backend.app.browser_v2.diagnostics import capture_bundle

    if not service.manager.running:
        return {"skipped": "browser_not_running (API/feed-only path)"}
    try:
        profile, _ = await service.store.load_profile()
        return await capture_bundle(await service.manager.page(), portal, service.adapters.get(portal),
                                    dry_run=True, profile=profile)
    except Exception as exc:  # noqa: BLE001 - diagnostics never break the run
        return {"error": type(exc).__name__}


async def check_session(portal: str, restart: bool, debug_selectors: bool = False) -> int:
    from backend.app.browser_v2.service import build_service

    service, backend = await build_service(require_db=False)
    try:
        first = await service.check_portal_session(portal)
        result: dict[str, Any] = {"store": backend, "first": first}
        if debug_selectors:
            result["diagnostics"] = [await debug_bundle(service, portal)]
        if restart:
            await service.manager.close()
            result["after_restart"] = await service.check_portal_session(portal)
        emit(result)
        final = result.get("after_restart", first)
        return 0 if final["status"] == "OK" else 1
    finally:
        await service.manager.close()
        await service.store.close()


async def default_query(service: Any) -> str:
    profile, _ = await service.store.load_profile()
    roles = (profile.get("preferences") or {}).get("target_roles") or []
    return roles[0] if roles else "software engineer"


SYNTHETIC_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def synthetic_profile() -> dict[str, Any]:
    """Fictional identity for dry-run form calibration only (example.com, placeholder PDF, never submitted)."""
    folder = brave_profile.runtime_dir() / "receipts" / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    resume = folder / "synthetic-resume.pdf"
    resume.write_bytes(SYNTHETIC_PDF)
    return {"full_name": "Test Candidate", "email": "candidate@example.com", "phone": "+910000000000",
            "linkedin_url": "https://www.linkedin.com/in/example", "verified_skills": ["Python", "FastAPI"],
            "preferences": {"current_location": "Bengaluru", "total_experience_years": 2, "notice_period_days": 30,
                            "willing_to_relocate": True, "resume_files": {"backend": str(resume)},
                            "target_roles": ["software engineer", "backend engineer", "engineer"]}}


async def test_apply(portal: str, live: bool, limit: int, query: str | None, url: str | None,
                     assume_yes: bool, boards: list[str] | None = None, debug_selectors: bool = False,
                     synthetic: bool = False) -> int:
    from backend.app.browser_v2.service import build_service
    from backend.app.browser_v2.state import NEVER_REPLAY

    if live and debug_selectors:
        emit({"error": "--debug-selectors is allowed only with --dry-run (never on a live submit)"})
        return 2
    if live and synthetic:
        emit({"error": "--synthetic-profile is allowed only with --dry-run"})
        return 2
    if live and limit > PHASE1_LIVE_LIMIT:
        emit({"error": f"Phase 1 allows at most {PHASE1_LIVE_LIMIT} watched live apply per run"})
        return 2
    service, backend = await build_service(require_db=live)
    results: list[dict[str, Any]] = []
    calibration: str | None = None
    try:
        from backend.app.browser_v2.store import MemoryStore

        memory = service.store if isinstance(service.store, MemoryStore) else None
        if debug_selectors and not live and memory is not None:
            # Pre-migration calibration only: the throwaway MemoryStore seeds just Naukri as enabled.
            # Enable the target portal IN MEMORY so a dry-run reaches the form (never Postgres, never live).
            from dataclasses import replace as dc_replace

            current = await memory.get_rules(portal)
            if not current.enabled:
                memory.rules[portal] = dc_replace(current, enabled=True, auto_apply_enabled=True,
                                                         active_hours_start=None, active_hours_end=None)
                calibration = "memory-only: portal enabled for this dry-run calibration (DB rules untouched)"
        if synthetic:
            if memory is None or live:
                emit({"error": "--synthetic-profile needs the pre-migration memory store and --dry-run"})
                return 2
            memory.profile = synthetic_profile()
            calibration = (calibration or "memory-only") + "; synthetic example.com profile (never submitted)"
        await service.configure_adapters()
        adapter = service.adapters.get(portal)
        if boards and adapter is not None and hasattr(adapter, "boards"):
            adapter.boards.update({board: None for board in boards})
        session = await service.check_portal_session(portal)
        if session.get("status") != "OK":
            # Fail closed before discovery: never parse a login wall / challenge page as job cards.
            result: dict[str, Any] = {"store": backend, "mode": "live" if live else "dry_run", "session": session,
                                      "results": [], "stopped": "session_not_ok"}
            if debug_selectors:
                result["diagnostics"] = [await debug_bundle(service, portal)]
            emit(result)
            return 1
        if url:
            targets = [url]
        else:
            search = query or await default_query(service)
            listings = await service.discover_portal_jobs(portal, search, limit=20)
            targets = [item["url"] for item in listings if item["state"] not in NEVER_REPLAY]
        if live and not assume_yes:
            answer = input(f"LIVE apply on {portal} (store={backend}). Type APPLY to continue: ")
            if answer.strip() != "APPLY":
                emit({"aborted": True})
                return 1
        applied = 0
        for target in targets[: limit * MAX_INSPECTIONS_PER_APPLY]:
            outcome = await service.apply_to_job(portal, target, dry_run=not live)
            if debug_selectors and len(results) < MAX_DEBUG_BUNDLES:
                outcome = dict(outcome) | {"diagnostics": await debug_bundle(service, portal)}
            results.append(outcome)
            reached_apply = outcome.get("reason") in {"dry_run_stopped_before_apply_click",
                                                      "dry_run_stopped_before_submit"} or outcome.get("clicked_apply")
            if reached_apply or outcome.get("state") in {"APPLIED", "WAITING_FOR_USER",
                                                         "SUBMISSION_UNKNOWN", "QUOTA_HIT_PENDING"}:
                applied += 1
            if applied >= limit:
                break
        emit({"store": backend, "mode": "live" if live else "dry_run",
              **({"calibration_rules": calibration} if calibration else {}), "results": results})
        return 0
    finally:
        await service.manager.close()
        await service.store.close()


async def mail_status_command(probe: bool, mail_app: bool, recent: int) -> int:
    """Draft bridge config + READ_AND_DRAFT_ONLY lock; --probe logs in (EXAMINE only), never writes."""
    from backend.app.ai_v2.router import load_env
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.imap_drafts import ImapDraftClient
    from backend.app.mail_v2.mail_app_drafts import MailAppDraftClient

    config = MailConfig.from_env(load_env())
    result: dict[str, Any] = {"permission": "READ_AND_DRAFT_ONLY",
                              "label": "Gmail Permission: Read + Draft Only (Sending Disabled)",
                              "config": config.public()}
    if probe and config.imap_configured:
        result["imap"] = await ImapDraftClient(config).check_connection()
    if recent and config.imap_configured:
        try:
            result["recent_drafts"] = await ImapDraftClient(config).list_recent_drafts(recent)
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            result["recent_drafts_error"] = type(exc).__name__
    if mail_app:
        result["mail_app"] = await MailAppDraftClient(config).probe()
    emit(result)
    return 0 if config.active_channel() != "unconfigured" else 1


async def test_draft_command(to: str, company: str, role: str, jd_file: str | None, dry_run: bool,
                             no_llm: bool) -> int:
    """Compose one tailored draft and save it as a clearly marked [TEST DRAFT] (or preview with --dry-run)."""
    from pathlib import Path

    from backend.app.ai_v2.router import load_env
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.service import open_store
    from backend.app.mail_v2.composer import DraftComposer, DraftJob
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.message import (
        TEST_SUBJECT_PREFIX,
        DraftValidationError,
        valid_recipient,
    )
    from backend.app.mail_v2.service import MailDraftService

    try:
        recipient = valid_recipient(to)
    except DraftValidationError as exc:
        emit({"saved": False, "error": str(exc)})
        return 2
    jd_text = Path(jd_file).read_text(encoding="utf-8")[:20_000] if jd_file else None
    env = load_env()
    store, backend = await open_store(require_db=False)
    try:
        profile, _ = await store.load_profile()
        router = None
        if not no_llm:
            ai = await AIRuntime.for_store(store, env=env)
            ai.bind_profile(profile)
            router = ai.router
        config = MailConfig.from_env(env)
        mail = MailDraftService(store, config)
        content = await DraftComposer(router).compose(
            DraftJob(role_title=role, company_name=company, jd_text=jd_text), profile,
            has_attachment=bool(config.resume_path))
        preview = {"to": recipient, "subject": TEST_SUBJECT_PREFIX + content.subject, "body": content.body,
                   "composer": content.composer, "llm_provider": content.provider,
                   "channel": config.active_channel(), "store": backend.split(" ")[0]}
        if dry_run:
            emit({"dry_run": True, "saved": False, "preview": preview})
            return 0
        outcome = await mail.save_test_draft(recipient, content,
                                             sender_name=profile.get("full_name") if profile else None)
        emit({"dry_run": False, "saved": outcome.created, **outcome.public(), "preview": preview,
              "note": "Draft only. Review it in Gmail > Drafts; nothing was delivered."})
        return 0 if outcome.created else 1
    finally:
        await store.close()


async def enrichment_status_command() -> int:
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.service import open_store
    from backend.app.enrichment_v2.service import EnrichmentService

    store, backend = await open_store(require_db=False)
    try:
        service = await EnrichmentService.for_store(store, env=load_env())
        emit({"store": backend, **await service.status()})
        return 0
    finally:
        await store.close()


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


async def ai_status_command(load_embedder: bool) -> int:
    """Configured providers, failover order and embedding-model readiness (no LLM calls)."""
    from backend.app.ai_v2.embeddings import FastEmbedder
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        embedder = ai.cache.embedder
        embed_info: dict[str, Any] = {"model": embedder.model_name, "loaded": embedder.ready}
        if isinstance(embedder, FastEmbedder):
            embed_info |= {"cache_dir": str(embedder.cache_dir), "downloaded": embedder.downloaded()}
        if load_embedder:
            vector = await embedder.embed("warm up the local embedding model")
            embed_info |= {"loaded": embedder.ready, "dimensions": len(vector)}
        status = await ai.status()
        from backend.app.browser_v2.env_loader import key_sources

        key_names = sorted({k for config in ai.router.providers.values()
                            for k in (*config.spec.key_envs, *config.spec.required_envs)})
        emit({"store": backend, "cache_backend": ai.cache.store.backend, "usage_backend": ai.router.usage.backend,
              "key_sources": key_sources(key_names),
              "embedding": embed_info,
              "configured_failover": {task: ai.router.configured_chain(task) for task in ai.router.chains},
              **status})
        return 0
    finally:
        await store.close()


async def ai_test_command(only: list[str]) -> int:
    """Live 1-request JSON health probe per configured free provider (zero PII, ~20 tokens each)."""
    from backend.app.ai_v2.probe import probe_all
    from backend.app.ai_v2.router import LLMRouter
    from backend.app.browser_v2.env_loader import env_layers, key_sources, load_env

    layers = env_layers()
    router = LLMRouter(env=load_env())
    names = sorted({k for config in router.providers.values()
                    for k in (*config.spec.key_envs, *config.spec.required_envs)})
    report = await probe_all(router.providers, only=only)
    emit({"env_layers": [layer.label + (f" ({layer.path.name})" if layer.path else "") for layer in layers],
          "key_sources": key_sources(names, layers=layers), **report})
    return 0 if report["configured"] == 0 or report["passed"] == report["configured"] else 1


async def seed_cache_command() -> int:
    """Idempotently import reviewed application_answer_drafts into semantic_cache (source='profile')."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.ai_v2.semantic_cache import seed_semantic_cache
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        _, reviewed = await store.load_profile()
        counts = await seed_semantic_cache(ai.cache, reviewed)
        persisted = ai.cache.store.backend == "postgres"
        emit({"store": backend, "cache_backend": ai.cache.store.backend, **counts,
              "stats": await ai.cache.stats(),
              **({} if persisted else {"warning": "semantic_cache table unavailable: seeded in memory only "
                                                  "(apply migration 004 with pgvector)"})})
        return 0 if persisted or backend != "postgres" else 1
    finally:
        await store.close()


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


async def export_sft_command(out: str) -> int:
    """PII-scrubbed, human-verified Q&A -> chat-completion JSONL (0600) for future fine-tuning."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.ai_v2.sft_export import export_sft_dataset
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, reviewed = await store.load_profile()
        result = await export_sft_dataset(out, cache_store=ai.cache.store, reviewed=reviewed, profile=profile)
        emit({"store": backend, "cache_backend": ai.cache.store.backend, **result})
        return 0
    finally:
        await store.close()


async def agent_chat_command(text: str) -> int:
    """Run the LangGraph control agent once (same tools + guardrails as Telegram free chat)."""
    from backend.app.agent_v2.control_graph import ControlAgent
    from backend.app.browser_v2.service import build_ai, open_store

    store, backend = await open_store(require_db=False)
    try:
        agent = ControlAgent(store, ai=await build_ai(store))
        emit({"store": backend, **await agent.run(text)})
        return 0
    finally:
        await store.close()


async def test_qa_command(question: str, options: list[str], no_llm: bool, no_save: bool) -> int:
    """Run Tier 0 -> 1 -> 2 -> 3 for one question and print which tier answered."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.answers import CandidateFacts
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, reviewed = await store.load_profile()
        ai.bind_profile(profile)
        ai.answerer.save_llm_answers = not no_save
        if no_llm:
            ai.answerer.router = None
        resolved = await ai.answerer.resolve(question, tuple(options), CandidateFacts.from_profile(profile, reviewed))
        emit({"store": backend, "cache_backend": ai.cache.store.backend, "question": question,
              "options": options, "tier": resolved.tier,
              "tier_name": {0: "profile_facts", 1: "semantic_cache", 2: "free_llm", 3: "human_hitl"}[resolved.tier],
              "cache_hit": resolved.tier == 1, **resolved.public()})
        return 0
    finally:
        await store.close()


async def telegram_status_command(probe: bool) -> int:
    """Config (token never printed, chat id masked), persisted poll state, optional live probe."""
    from backend.app.browser_v2.service import open_store
    from backend.app.telegram_v2.bot import telegram_status
    from backend.app.telegram_v2.client import (
        TelegramClient,
        TelegramConflict,
        TelegramError,
    )
    from backend.app.telegram_v2.config import TelegramConfig

    config = TelegramConfig.from_env()
    store, backend = await open_store(require_db=False)
    try:
        result: dict[str, Any] = {"store": backend, "config": config.public(),
                                  "state": await telegram_status(store, config)}
        if probe and config.configured and config.token:
            client = TelegramClient(config.token)
            checks: dict[str, Any] = {}
            try:
                me = await client.get_me()
                checks["bot_username"] = me.get("username")
                webhook = await client.get_webhook_info()
                checks["webhook_set"] = bool(webhook.get("url"))
                # No offset -> confirms nothing; a running poller may see one harmless 409.
                await client.get_updates(None, timeout=0, limit=1)
                checks["conflict"] = False
            except TelegramConflict:
                checks["conflict"] = True
                checks["hint"] = ("another poller is using this token (likely com.automated-apply.rust); "
                                  "launchctl bootout gui/$(id -u)/com.automated-apply.rust to free it")
            except TelegramError as exc:
                checks["error"] = exc.code
            finally:
                await client.aclose()
            result["probe"] = checks
        emit(result)
        return 0 if config.configured else 1
    finally:
        await store.close()


async def telegram_test_command() -> int:
    """Send one test ping to the owner chat (verifies token + chat id live)."""
    from backend.app.browser_v2.store import MemoryStore
    from backend.app.telegram_v2.bot import TelegramBot
    from backend.app.telegram_v2.client import TelegramError
    from backend.app.telegram_v2.config import TelegramConfig

    config = TelegramConfig.from_env()
    if not config.configured:
        emit({"sent": False, "config": config.public()})
        return 1
    bot = TelegramBot(config, MemoryStore())
    assert bot.client is not None
    try:
        emit(await bot.send_test_ping() | {"owner_chat_id": config.masked_chat_id()})
        return 0
    except TelegramError as exc:
        emit({"sent": False, "error": exc.code})
        return 1
    finally:
        await bot.client.aclose()


async def health_check_command(as_json: bool, include_db: bool) -> int:
    from backend.app.browser_v2.health import render_text, run_health

    report = await run_health(include_db=include_db)
    print(json.dumps(report, indent=2, default=str) if as_json else render_text(report))
    return 0 if report["ok"] else 1


async def apply_one_command(portal: str, url: str, confirm_live: bool, assume_yes: bool) -> int:
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.canary import apply_one
    from backend.app.browser_v2.worker import quota_notifier

    notify, close = quota_notifier(load_env())
    try:
        report = await apply_one(portal, url, confirm_live=confirm_live, assume_yes=assume_yes, notify=notify)
    finally:
        if close is not None:
            await close()
    emit(report)
    return 0 if report.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="browser_v2", description="Dedicated Brave profile tools")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login-setup", help="open plain Brave on the dedicated profile")
    login.add_argument("--portal", action="append", choices=sorted(brave_profile.LOGIN_URLS),
                       help="repeatable; default: portals with a live adapter (naukri)")
    login.add_argument("--all", action="store_true", help="open all 8 browser-portal login pages")
    check = commands.add_parser("check-session", help="verify the persistent login")
    check.add_argument("--portal", default="naukri", choices=sorted(PORTALS))
    check.add_argument("--restart", action="store_true", help="also verify after a browser restart")
    check.add_argument("--debug-selectors", action="store_true",
                       help="save a PII-scrubbed DOM probe + screenshot under receipts/diagnostics/")
    apply = commands.add_parser("test-apply", help="discover and apply (dry-run or one live)")
    apply.add_argument("--portal", default="naukri", choices=sorted(PORTALS))
    apply.add_argument("--board", action="append", default=[],
                       help="greenhouse/lever board token for this run (repeatable; else preferences)")
    mode = apply.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    apply.add_argument("--limit", type=int, default=1)
    apply.add_argument("--query", help="search keywords (default: first preferences.target_roles)")
    apply.add_argument("--url", help="apply to this exact job URL instead of searching")
    apply.add_argument("--yes", action="store_true", help="skip the typed live confirmation")
    apply.add_argument("--synthetic-profile", action="store_true",
                       help="dry-run + memory store only: fictional example.com identity to calibrate form filling")
    apply.add_argument("--debug-selectors", action="store_true",
                       help="dry-run only: save PII-scrubbed DOM probe bundles (max 3) under receipts/diagnostics/")
    worker = commands.add_parser("worker", help="24/7 loop driven by public.worker_control")
    worker.add_argument("--dry-run", action="store_true",
                        help="never click Apply (also forced by DRY_RUN=true)")
    worker.add_argument("--once", action="store_true", help="run exactly one cycle now, then exit")
    worker.add_argument("--no-telegram", action="store_true",
                        help="do not run the Telegram HITL poller/dispatcher (isolated debugging)")
    tg_status = commands.add_parser("telegram-status", help="Telegram HITL config, poll offset and conflict state")
    tg_status.add_argument("--probe", action="store_true",
                           help="also call getMe/getWebhookInfo/getUpdates live to detect a 409 conflict")
    commands.add_parser("telegram-test", help="send one test ping to the owner chat")
    commands.add_parser("mcp", help="serve the browser tools over FastMCP stdio")
    status = commands.add_parser("ai-status", help="free LLM providers, failover order, embedding model")
    status.add_argument("--load-embedder", action="store_true",
                        help="load (and on first use download, ~80 MB) the local ONNX embedding model")
    ai_test = commands.add_parser("ai-test", help="live 1-request JSON probe of each configured free LLM provider")
    ai_test.add_argument("--provider", action="append", default=[], help="limit to this provider (repeatable)")
    commands.add_parser("seed-cache", help="seed semantic_cache from reviewed application_answer_drafts")
    qa = commands.add_parser("test-qa", help="run the 4-tier screening answer pipeline for one question")
    qa.add_argument("--question", required=True)
    qa.add_argument("--option", action="append", default=[], help="a choice option (repeatable)")
    qa.add_argument("--no-llm", action="store_true", help="stop after Tier 1 (no external LLM call)")
    qa.add_argument("--no-save", action="store_true", help="do not cache an accepted LLM answer")
    mail = commands.add_parser("mail-status", help="Gmail draft bridge (IMAP / Mail.app), READ + DRAFT ONLY")
    mail.add_argument("--probe", action="store_true", help="IMAP login + read-only EXAMINE of Drafts")
    mail.add_argument("--mail-app", action="store_true",
                      help="probe Mail.app scripting (may show the one-time macOS Automation prompt)")
    mail.add_argument("--recent", type=int, default=0, help="list N recent Gmail draft headers (read-only)")
    draft = commands.add_parser("test-draft", help="compose + save one [TEST DRAFT] in Gmail Drafts (never delivered)")
    draft.add_argument("--to", required=True)
    draft.add_argument("--company", required=True)
    draft.add_argument("--role", required=True)
    draft.add_argument("--jd-file", help="optional plain-text JD to tailor the draft")
    draft.add_argument("--dry-run", action="store_true", help="print the composed draft; save nothing")
    draft.add_argument("--no-llm", action="store_true", help="deterministic template only")
    commands.add_parser("enrichment-status", help="Apollo/Apify/SignalHire config + today's free credits")
    smoke = commands.add_parser("live-smoke", help="opt-in non-destructive live checks (JSON report)")
    smoke.add_argument("--check", action="append", choices=["db", "browser", "ai", "telegram", "mail",
                                                            "enrichment"],
                       help="repeatable; default: db ai telegram mail enrichment (browser is opt-in)")
    smoke.add_argument("--mail-app", action="store_true", help="also probe Mail.app scripting")
    smoke.add_argument("--no-llm-ping", action="store_true", help="skip the 1-request free LLM health ping")
    smoke.add_argument("--portal", default="naukri", choices=["naukri"])
    cred = commands.add_parser("set-portal-cred", help="store a portal login in the macOS Keychain (auto re-login)")
    cred.add_argument("--portal", required=True, choices=sorted(PORTALS))
    sft = commands.add_parser("export-sft-dataset", help="PII-scrubbed verified Q&A -> chat JSONL for fine-tuning")
    sft.add_argument("--out", required=True, help="output .jsonl path (written 0600)")
    chat = commands.add_parser("agent-chat", help="one message to the LangGraph control agent")
    chat.add_argument("text")
    one = commands.add_parser("apply-one", help="Phase 8 canary: ONE job by URL (dry-run unless --confirm-live)")
    one.add_argument("--portal", required=True, choices=sorted(PORTALS))
    one.add_argument("--url", required=True, help="exact job URL on that portal")
    one.add_argument("--confirm-live", action="store_true",
                     help="really apply (still asks you to type 'APPLY <portal>'); default is a dry-run")
    one.add_argument("--yes", action="store_true", help="with --confirm-live: skip the typed confirmation")
    from backend.app.browser_v2 import facts_cli

    facts_cli.register(commands)
    health = commands.add_parser("health-check", help="non-destructive 24/7 watchdog report (Phase 6B)")
    health.add_argument("--json", action="store_true", help="machine-readable JSON")
    health.add_argument("--no-db", action="store_true", help="skip the single read-only DB probe")
    args = parser.parse_args(argv)
    try:
        if args.command == "set-portal-cred":
            return set_portal_cred_command(args.portal)
        if args.command == "export-sft-dataset":
            return asyncio.run(export_sft_command(args.out))
        if args.command == "agent-chat":
            return asyncio.run(agent_chat_command(args.text))
        if args.command == "health-check":
            return asyncio.run(health_check_command(args.json, not args.no_db))
        if args.command == "apply-one":
            return asyncio.run(apply_one_command(args.portal, args.url, args.confirm_live, args.yes))
        if args.command == "facts":
            from backend.app.browser_v2 import facts_cli as facts_module

            return facts_module.run(args)
        if args.command == "login-setup":
            from backend.app.browser_v2.portals import LOGIN_PORTALS

            portals = sorted(brave_profile.LOGIN_URLS) if args.all else (args.portal or sorted(LOGIN_PORTALS))
            return login_setup(portals)
        if args.command == "mail-status":
            return asyncio.run(mail_status_command(args.probe, args.mail_app, max(0, min(args.recent, 50))))
        if args.command == "test-draft":
            return asyncio.run(test_draft_command(args.to, args.company, args.role, args.jd_file, args.dry_run,
                                                  args.no_llm))
        if args.command == "enrichment-status":
            return asyncio.run(enrichment_status_command())
        if args.command == "live-smoke":
            checks = args.check or ["db", "ai", "telegram", "mail", "enrichment"]
            return asyncio.run(live_smoke_command(checks, args.mail_app, not args.no_llm_ping, args.portal))
        if args.command == "check-session":
            return asyncio.run(check_session(args.portal, args.restart, args.debug_selectors))
        if args.command == "test-apply":
            return asyncio.run(test_apply(args.portal, args.live, max(1, args.limit), args.query,
                                          args.url, args.yes, boards=args.board,
                                          debug_selectors=args.debug_selectors,
                                          synthetic=args.synthetic_profile))
        if args.command == "worker":
            return asyncio.run(run_worker_command(args.dry_run, args.once, telegram=not args.no_telegram))
        if args.command == "telegram-status":
            return asyncio.run(telegram_status_command(args.probe))
        if args.command == "telegram-test":
            return asyncio.run(telegram_test_command())
        if args.command == "ai-status":
            return asyncio.run(ai_status_command(args.load_embedder))
        if args.command == "ai-test":
            return asyncio.run(ai_test_command(args.provider))
        if args.command == "seed-cache":
            return asyncio.run(seed_cache_command())
        if args.command == "test-qa":
            return asyncio.run(test_qa_command(args.question, args.option, args.no_llm, args.no_save))
        from backend.app.browser_v2.browser_mcp import mcp

        mcp.run()
        return 0
    except brave_profile.ProfileError as exc:
        emit({"error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
