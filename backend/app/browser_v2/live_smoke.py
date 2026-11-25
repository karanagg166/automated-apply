"""Opt-in, non-destructive live diagnostics (CLI `live-smoke` and `pytest -m live`).

Never submits an application, never creates or delivers an email, never writes to
Supabase. Each check returns {"check", "ok", "skipped", "details"} and never raises.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

CHECKS = ("db", "browser", "ai", "telegram", "mail", "enrichment")


class _Ping(BaseModel):
    ok: bool


def _result(check: str, ok: bool, details: dict[str, Any], *, skipped: str | None = None,
            started: float | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {"check": check, "ok": ok, "skipped": skipped, "details": details}
    if started is not None:
        output["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return output


async def check_db(env_file: str | None = None) -> dict[str, Any]:
    from backend.app.browser_v2.config import load_settings
    from backend.app.browser_v2.store import PostgresStore

    started = time.perf_counter()
    try:
        store = await PostgresStore.connect(load_settings(env_file))
    except Exception as exc:  # noqa: BLE001 - a diagnostic reports, never crashes
        return _result("db", False, {"error": f"{type(exc).__name__}: {str(exc)[:160]}",
                                     "hint": "apply migration 004 (migrate_v2_core check, then apply)"},
                       started=started)
    try:
        connection = store.connection
        tables = await connection.fetchrow(
            """SELECT to_regclass('public.email_drafts') IS NOT NULL AS email_drafts,
                      to_regclass('public.enrichment_cache') IS NOT NULL AS enrichment_cache,
                      to_regclass('public.enrichment_credits') IS NOT NULL AS enrichment_credits,
                      to_regclass('public.semantic_cache') IS NOT NULL AS semantic_cache,
                      to_regclass('public.telegram_v2_state') IS NOT NULL AS telegram_v2_state""")
        portals = await connection.fetchval("SELECT count(*) FROM public.portal_rules")
        details = {"schema_ready": True, **dict(tables), "portal_rules": portals}
        return _result("db", all(dict(tables).values()) and portals >= 1, details, started=started)
    finally:
        await store.close()


async def check_browser(portal: str = "naukri") -> dict[str, Any]:
    from backend.app.browser_v2.manager import BraveBrowserManager
    from backend.app.browser_v2.service import BrowserService
    from backend.app.browser_v2.store import MemoryStore

    started = time.perf_counter()
    service = BrowserService(BraveBrowserManager(), MemoryStore())  # read-only session probe; no DB writes
    try:
        session = await service.check_portal_session(portal)
        return _result("browser", session.get("status") == "OK", {"portal": portal, **session}, started=started)
    except Exception as exc:  # noqa: BLE001 - a diagnostic reports, never crashes
        return _result("browser", False, {"portal": portal, "error": f"{type(exc).__name__}: {str(exc)[:160]}"},
                       started=started)
    finally:
        await service.manager.close()


async def check_ai(env_file: str | None = None, *, llm_ping: bool = True) -> dict[str, Any]:
    from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, load_env
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.store import MemoryStore

    started = time.perf_counter()
    try:
        ai = await AIRuntime.for_store(MemoryStore(), env=load_env(env_file))
        vector = await ai.cache.embedder.embed("warm up the local embedding model")
        details: dict[str, Any] = {"embedding_model": ai.cache.embedder.model_name, "dimensions": len(vector),
                                   "configured": {t: ai.router.configured_chain(t) for t in ai.router.chains}}
        ok = len(vector) == 384
        if llm_ping and ai.router.any_configured:
            try:
                reply = await ai.router.generate_json("screening_qa", "Return JSON only.",
                                                      'Reply with {"ok": true}.', _Ping, max_output_tokens=20)
                details["llm_ping"] = {"provider": reply.provider, "model": reply.model,
                                       "latency_ms": round(reply.latency_ms), "ok": reply.value.ok}
            except AllLLMProvidersExhaustedError as exc:
                details["llm_ping"] = {"ok": False, "attempts": exc.attempts}
                ok = False
        elif llm_ping:
            details["llm_ping"] = {"skipped": "no free LLM provider configured"}
        return _result("ai", ok, details, started=started)
    except Exception as exc:  # noqa: BLE001 - a diagnostic reports, never crashes
        return _result("ai", False, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}, started=started)


async def check_telegram(env_file: str | None = None) -> dict[str, Any]:
    from backend.app.ai_v2.router import load_env
    from backend.app.telegram_v2.client import (
        TelegramClient,
        TelegramConflict,
        TelegramError,
    )
    from backend.app.telegram_v2.config import TelegramConfig

    started = time.perf_counter()
    config = TelegramConfig.from_env(load_env(env_file))
    if not config.configured or not config.token:
        return _result("telegram", False, {"config": config.public()}, skipped="unconfigured", started=started)
    client = TelegramClient(config.token)
    details: dict[str, Any] = {}
    try:
        details["bot_username"] = (await client.get_me()).get("username")
        await client.get_updates(None, timeout=0, limit=1)  # confirms nothing (no offset)
        details["conflict"] = False
        return _result("telegram", True, details, started=started)
    except TelegramConflict:
        details |= {"conflict": True, "hint": "another poller (likely com.automated-apply.rust) holds the token"}
        return _result("telegram", False, details, started=started)
    except TelegramError as exc:
        return _result("telegram", False, details | {"error": exc.code}, started=started)
    finally:
        await client.aclose()


async def check_mail(env_file: str | None = None, *, mail_app: bool = False) -> dict[str, Any]:
    from backend.app.ai_v2.router import load_env
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.imap_drafts import ImapDraftClient
    from backend.app.mail_v2.mail_app_drafts import MailAppDraftClient

    started = time.perf_counter()
    config = MailConfig.from_env(load_env(env_file))
    details: dict[str, Any] = {"config": config.public()}
    ok = False
    if config.imap_configured:
        details["imap"] = await ImapDraftClient(config).check_connection()  # login + EXAMINE only
        ok = bool(details["imap"].get("ok"))
    if mail_app:
        details["mail_app"] = await MailAppDraftClient(config).probe()
        ok = ok or bool(details["mail_app"].get("ok"))
    if not config.imap_configured and not mail_app:
        return _result("mail", False, details, skipped="imap_unconfigured (pass --mail-app to probe Mail.app)",
                       started=started)
    return _result("mail", ok, details, started=started)


async def check_enrichment(env_file: str | None = None) -> dict[str, Any]:
    """Config + today's credits only: no provider is called (credits are never spent here)."""
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.service import open_store
    from backend.app.enrichment_v2.service import EnrichmentService

    started = time.perf_counter()
    store, backend = await open_store(require_db=False, env_file=env_file)
    try:
        service = await EnrichmentService.for_store(store, env=load_env(env_file))
        status = await service.status()
        return _result("enrichment", True, {"store": backend.split(" ")[0], **status}, started=started)
    finally:
        await store.close()


async def run_live_smoke(checks: list[str], *, env_file: str | None = None, mail_app: bool = False,
                         llm_ping: bool = True, portal: str = "naukri") -> dict[str, Any]:
    runners: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
        "db": lambda: check_db(env_file),
        "browser": lambda: check_browser(portal),
        "ai": lambda: check_ai(env_file, llm_ping=llm_ping),
        "telegram": lambda: check_telegram(env_file),
        "mail": lambda: check_mail(env_file, mail_app=mail_app),
        "enrichment": lambda: check_enrichment(env_file),
    }
    results = []
    for name in checks:
        try:
            results.append(await runners[name]())
        except Exception as exc:  # noqa: BLE001 - a diagnostic reports, never crashes
            results.append(_result(name, False, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}))
    return {"generated_at": datetime.now(UTC).isoformat(), "checks": results,
            "ok": all(r["ok"] or r["skipped"] for r in results),
            "guarantees": ["no application submitted", "no email created or delivered", "no database writes"]}
