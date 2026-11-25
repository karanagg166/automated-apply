"""Owner CLI for the dedicated Brave profile and the Naukri adapter.

Run from the repository root:
    backend/venv/bin/python -m backend.app.browser_v2.cli login-setup
    backend/venv/bin/python -m backend.app.browser_v2.cli check-session --portal naukri --restart
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --dry-run --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --live --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run --once
    backend/venv/bin/python -m backend.app.browser_v2.cli mcp
    backend/venv/bin/python -m backend.app.browser_v2.cli ai-status [--load-embedder]
    backend/venv/bin/python -m backend.app.browser_v2.cli seed-cache
    backend/venv/bin/python -m backend.app.browser_v2.cli test-qa --question "..." [--option Yes --option No]
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run [--no-telegram]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-status [--probe]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from typing import Any

from backend.app.browser_v2 import profile as brave_profile

PHASE1_LIVE_LIMIT = 1
MAX_INSPECTIONS_PER_APPLY = 10


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def login_setup(portals: list[str]) -> int:
    """Plain Brave (no Playwright/CDP/automation flags) so portals see a normal browser."""
    path = brave_profile.ensure_profile_dir()
    brave_profile.assert_profile_free(path)
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


async def check_session(portal: str, restart: bool) -> int:
    from backend.app.browser_v2.service import build_service

    service, backend = await build_service(require_db=False)
    try:
        first = await service.check_portal_session(portal)
        result: dict[str, Any] = {"store": backend, "first": first}
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


async def test_apply(portal: str, live: bool, limit: int, query: str | None, url: str | None,
                     assume_yes: bool) -> int:
    from backend.app.browser_v2.service import build_service
    from backend.app.browser_v2.state import NEVER_REPLAY

    if live and limit > PHASE1_LIVE_LIMIT:
        emit({"error": f"Phase 1 allows at most {PHASE1_LIVE_LIMIT} watched live apply per run"})
        return 2
    service, backend = await build_service(require_db=live)
    results: list[dict[str, Any]] = []
    try:
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
            results.append(outcome)
            reached_apply = outcome.get("reason") == "dry_run_stopped_before_apply_click" or outcome.get(
                "clicked_apply")
            if reached_apply or outcome.get("state") in {"APPLIED", "WAITING_FOR_USER",
                                                         "SUBMISSION_UNKNOWN", "QUOTA_HIT_PENDING"}:
                applied += 1
            if applied >= limit:
                break
        emit({"store": backend, "mode": "live" if live else "dry_run", "results": results})
        return 0
    finally:
        await service.manager.close()
        await service.store.close()


async def run_worker_command(dry_run: bool, once: bool, telegram: bool = True) -> int:
    import logging

    from backend.app.browser_v2.service import plain
    from backend.app.browser_v2.worker import run_worker
    from backend.app.telegram_v2.client import install_log_redaction

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_log_redaction()  # httpx logs request URLs at INFO; the Telegram URL contains the token
    reports = await run_worker(dry_run=dry_run, once=once, telegram=telegram)
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
        emit({"store": backend, "cache_backend": ai.cache.store.backend, "usage_backend": ai.router.usage.backend,
              "embedding": embed_info,
              "configured_failover": {task: ai.router.configured_chain(task) for task in ai.router.chains},
              **status})
        return 0
    finally:
        await store.close()


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="browser_v2", description="Dedicated Brave profile tools")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login-setup", help="open plain Brave on the dedicated profile")
    login.add_argument("--portal", action="append", choices=sorted(brave_profile.LOGIN_URLS))
    check = commands.add_parser("check-session", help="verify the persistent login")
    check.add_argument("--portal", default="naukri", choices=["naukri"])
    check.add_argument("--restart", action="store_true", help="also verify after a browser restart")
    apply = commands.add_parser("test-apply", help="discover and apply (dry-run or one live)")
    apply.add_argument("--portal", default="naukri", choices=["naukri"])
    mode = apply.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    apply.add_argument("--limit", type=int, default=1)
    apply.add_argument("--query", help="search keywords (default: first preferences.target_roles)")
    apply.add_argument("--url", help="apply to this exact job URL instead of searching")
    apply.add_argument("--yes", action="store_true", help="skip the typed live confirmation")
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
    commands.add_parser("seed-cache", help="seed semantic_cache from reviewed application_answer_drafts")
    qa = commands.add_parser("test-qa", help="run the 4-tier screening answer pipeline for one question")
    qa.add_argument("--question", required=True)
    qa.add_argument("--option", action="append", default=[], help="a choice option (repeatable)")
    qa.add_argument("--no-llm", action="store_true", help="stop after Tier 1 (no external LLM call)")
    qa.add_argument("--no-save", action="store_true", help="do not cache an accepted LLM answer")
    args = parser.parse_args(argv)
    try:
        if args.command == "login-setup":
            return login_setup(args.portal or sorted(brave_profile.LOGIN_URLS))
        if args.command == "check-session":
            return asyncio.run(check_session(args.portal, args.restart))
        if args.command == "test-apply":
            return asyncio.run(test_apply(args.portal, args.live, max(1, args.limit), args.query,
                                          args.url, args.yes))
        if args.command == "worker":
            return asyncio.run(run_worker_command(args.dry_run, args.once, telegram=not args.no_telegram))
        if args.command == "telegram-status":
            return asyncio.run(telegram_status_command(args.probe))
        if args.command == "telegram-test":
            return asyncio.run(telegram_test_command())
        if args.command == "ai-status":
            return asyncio.run(ai_status_command(args.load_embedder))
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
