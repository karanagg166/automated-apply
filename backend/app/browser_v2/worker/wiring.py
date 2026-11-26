"""Phase 9 worker-process services: fast-poll watchers, early-bird Telegram notifier and the
portal profile-sync scheduler.

All of them run inside the worker process and share its single serialized Supabase
connection (`service.store`) and its single Brave tab (profile sync only, between jobs).
Every piece is optional and fail-soft: a failure here is logged and never stops applying.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.app.browser_v2.worker.reports import logger


@dataclass
class Phase9Services:
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    profile_sync: Any = None

    async def aclose(self, stop: asyncio.Event, timeout: float = 10.0) -> None:
        stop.set()
        for task in self.tasks:
            try:
                await asyncio.wait_for(task, timeout=timeout)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
            except Exception as exc:  # noqa: BLE001
                logger.warning("phase9 task shutdown: %s", type(exc).__name__)
        for close in self.closers:
            with contextlib.suppress(Exception):
                await close()


async def _high_priority_pending(service: Any) -> bool:
    from datetime import UTC, datetime

    try:
        return bool(await service.store.priority_candidates(datetime.now(UTC), limit=1))
    except Exception:  # noqa: BLE001 - when unsure, let profile sync wait
        return True


def _start_watchers(service: Any, worker: Any, stop: asyncio.Event, out: Phase9Services) -> None:
    from backend.app.browser_v2.service.scoring import score_listing
    from backend.app.browser_v2.watchers import build_watcher_hub

    remotive = getattr(service, "adapters", {}).get("remotive")
    if remotive is not None and hasattr(remotive, "use_store"):
        remotive.use_store(service.store)  # Remotive's 4/day cap lives in Supabase, not in memory
    hub = build_watcher_hub(service.store, service=service, worker=worker,
                            bus=getattr(service, "event_bus", None), score_listing=score_listing)
    out.tasks.append(asyncio.create_task(hub.run(stop), name="phase9-watchers"))
    out.closers.append(hub.aclose)


def _start_notifier(service: Any, env: dict[str, str], out: Phase9Services) -> None:
    from backend.app.telegram_v2.client import TelegramClient
    from backend.app.telegram_v2.config import TelegramConfig
    from backend.app.telegram_v2.notifications import EarlyBirdNotifier, register

    bus = getattr(service, "event_bus", None)
    config = TelegramConfig.from_env(env)
    if bus is None or not config.configured or not config.token or config.owner_chat_id is None:
        return
    client = TelegramClient(config.token)
    notifier = EarlyBirdNotifier(client, config.owner_chat_id, store=service.store)
    register(bus, notifier)
    out.closers.append(client.aclose)


def _start_profile_sync(service: Any, worker: Any, out: Phase9Services) -> None:
    from backend.app.browser_v2.profile_sync.scheduler import build_profile_sync

    env_profile = getattr(service, "env_profile", {}) or {}
    scheduler = build_profile_sync(
        service.store, service.manager, session_adapters=getattr(service, "adapters", None),
        fallback_resume_path=env_profile.get("resume_path"),
        high_priority_pending=lambda: _high_priority_pending(service))
    worker.profile_sync = scheduler
    out.profile_sync = scheduler
    bus = getattr(service, "event_bus", None)
    if bus is not None:
        async def on_profile_updated(topic: str, payload: dict[str, Any]) -> None:
            await scheduler.on_event(topic, payload)

        with contextlib.suppress(Exception):
            bus.subscribe("profile.updated", on_profile_updated)


async def start_phase9_services(service: Any, worker: Any, env: dict[str, str], stop: asyncio.Event, *,
                                watchers: bool = True, telegram: bool = True) -> Phase9Services:
    out = Phase9Services()
    steps: list[tuple[str, Callable[[], None]]] = [
        ("profile_sync", lambda: _start_profile_sync(service, worker, out)),
    ]
    if telegram:
        steps.append(("early_bird_notifier", lambda: _start_notifier(service, env, out)))
    if watchers:
        steps.append(("watchers", lambda: _start_watchers(service, worker, stop, out)))
    for name, start in steps:
        try:
            start()
        except Exception as exc:  # noqa: BLE001 - optional services never stop the worker
            logger.warning("phase9 %s disabled for this run: %s", name, type(exc).__name__)
    return out
