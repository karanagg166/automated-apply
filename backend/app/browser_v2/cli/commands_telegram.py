"""Telegram HITL commands: telegram-status, telegram-test."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.cli.common import emit


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
                # Never call getUpdates here: it would steal the worker's long poll and make the
                # worker itself see a 409 (60 s inbound outage + a misleading diagnosis).
                checks["conflict"] = bool(result["state"].get("conflict_detected"))
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
