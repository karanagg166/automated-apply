"""Worker process wiring: Telegram sibling task, quota notifier and the `cli worker` entry point."""

from __future__ import annotations

import asyncio
import html
from collections.abc import Awaitable, Callable

from backend.app.browser_v2.quota import Notifier
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.worker.core import Worker
from backend.app.browser_v2.worker.reports import (
    CycleReport,
    env_forces_dry_run,
    logger,
)


async def start_telegram(service: BrowserService, stop: asyncio.Event,
                         env_file: str | None = None, *, worker: Worker | None = None,
                         profile_sync: object | None = None) -> asyncio.Task[None] | None:
    """Telegram HITL poller + dispatcher as a sibling task (unconfigured -> status only, no task)."""
    from backend.app.ai_v2.router import load_env
    from backend.app.telegram_v2.bot import TelegramBot
    from backend.app.telegram_v2.config import TelegramConfig

    try:
        reader = getattr(service, "mail_reader", None)
        bot = TelegramBot(TelegramConfig.from_env(load_env(env_file)), service.store, ai=service.ai,
                          event_bus=getattr(service, "event_bus", None),
                          mail_events=getattr(reader, "events", None),
                          agent_wake=(lambda: worker.wake("telegram_agent")) if worker is not None else None)
        bot.agent_profile_sync = profile_sync
        if not bot.config.configured:
            await bot.run(stop)  # records polling_state='unconfigured' and returns
            return None
        return asyncio.create_task(bot.run(stop), name="telegram-hitl")
    except Exception as exc:  # noqa: BLE001 - Telegram must never stop the application worker
        logger.warning("telegram_v2 disabled for this run: %s", type(exc).__name__)
        return None


async def stop_telegram(task: asyncio.Task[None] | None, stop: asyncio.Event, timeout: float = 10.0) -> None:
    if task is None:
        return
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_v2 shutdown: %s", type(exc).__name__)


async def run_worker(*, dry_run: bool, once: bool, env_file: str | None = None,
                     telegram: bool = True) -> list[CycleReport]:
    """CLI entry: Postgres-backed (worker state must persist), SIGTERM-safe."""
    import signal

    from backend.app.browser_v2.service import build_service

    # Live runs need the DB (worker_control persists desired state); a dry run may
    # fall back to memory before migration 004 so the loop can be smoke-tested.
    dry_run = dry_run or env_forces_dry_run()
    service, backend = await build_service(require_db=not dry_run, env_file=env_file)
    if backend != "postgres" and not once:
        raise RuntimeError("worker_requires_postgres: use --once for an in-memory dry run")
    if not await service.store.phase9_ready():
        # Phase 9B: priority/circuit/sweep columns are read every cycle; never run half-migrated.
        logger.error("worker refuses to start: Phase 9 migration missing - apply "
                     "supabase/fresh_public/followups/005_python_v2_phase9.sql, then restart the worker")
        try:
            await service.store.worker_heartbeat("OFFLINE", last_error="phase9_migration_missing")
        finally:
            bus = getattr(service, "event_bus", None)
            if bus is not None:
                await bus.close()
            await service.manager.close()
            await service.store.close()
        raise RuntimeError("phase9_migration_missing")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.quota import build_quota_processor

    env = load_env(env_file)
    quota = await build_quota_processor(service, env)
    notify, notify_close = quota_notifier(env) if telegram else (None, None)
    from backend.app.browser_v2.digest import DigestScheduler, digest_hour

    worker = Worker(service, force_dry_run=dry_run, stop_event=stop, quota=quota, notify=notify,
                    mail_reader=getattr(service, "mail_reader", None),
                    digest=DigestScheduler(service.store, hour=digest_hour(env)) if notify is not None else None)
    logger.info("worker store=%s dry_run=%s once=%s telegram=%s", backend, worker.force_dry_run, once, telegram)
    from backend.app.browser_v2.worker.wiring import start_phase9_services

    phase9_stop = asyncio.Event()
    phase9 = await start_phase9_services(service, worker, env, phase9_stop, watchers=not once, telegram=telegram)
    telegram_stop = asyncio.Event()
    telegram_task = await start_telegram(service, telegram_stop, env_file, worker=worker,
                                         profile_sync=phase9.profile_sync) if telegram else None
    try:
        return await worker.run(once=once)
    finally:  # watchers/notifier/profile-sync are cancelled and awaited before the store closes
        await stop_telegram(telegram_task, telegram_stop)
        await phase9.aclose(phase9_stop)
        if notify_close is not None:
            await notify_close()
        bus = getattr(service, "event_bus", None)
        if bus is not None:
            await bus.close()
        await service.manager.close()
        await service.store.close()


def quota_notifier(env: dict[str, str]) -> tuple[Notifier | None, Callable[[], Awaitable[None]] | None]:
    """Owner-chat summary when a portal hits its daily limit (None when Telegram is unconfigured)."""
    from backend.app.telegram_v2.client import TelegramClient
    from backend.app.telegram_v2.config import TelegramConfig

    config = TelegramConfig.from_env(env)
    if not config.configured or not config.token or config.owner_chat_id is None:
        return None, None
    client = TelegramClient(config.token)
    chat_id: int = config.owner_chat_id

    async def notify(text: str) -> None:
        await client.send_message(chat_id, html.escape(text, quote=False))  # parse_mode=HTML

    return notify, client.aclose
