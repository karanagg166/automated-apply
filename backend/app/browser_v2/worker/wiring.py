"""Phase 9 worker-process services: fast-poll watchers, the Telegram NotificationRouter and the
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
    notifier: Any = None

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


def _start_notifier(service: Any, worker: Any, env: dict[str, str], out: Phase9Services, client: Any) -> None:
    """The zero-spam NotificationRouter: every non-HITL Telegram notification goes through it."""
    from backend.app.telegram_v2.config import TelegramConfig
    from backend.app.telegram_v2.notify_policy import NotifyConfig
    from backend.app.telegram_v2.notify_router import NotificationRouter

    config = TelegramConfig.from_env(env)
    if client is None or not config.configured or config.owner_chat_id is None:
        return
    store = service.store

    async def prefs() -> dict[str, Any]:
        profile, _ = await store.load_profile()
        value = (profile or {}).get("preferences") if isinstance(profile, dict) else None
        return value if isinstance(value, dict) else {}

    router = NotificationRouter(client, config.owner_chat_id, store, NotifyConfig.from_env(env),
                                prefs_provider=prefs)
    bus = getattr(service, "event_bus", None)
    if bus is not None:
        router.register(bus)
    worker.notifier = router
    out.notifier = router
    out.closers.append(router.close)


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


def _start_outreach(service: Any, worker: Any, env: dict[str, str]) -> None:
    """Milestone 2: opt-in high-score outreach DRAFTS (default off; never sends)."""
    from backend.app.browser_v2.worker.outreach import OutreachHandoff

    handoff = OutreachHandoff.from_env(service.store, getattr(worker, "quota", None), env,
                                       publish=getattr(service, "publish", None))
    worker.outreach = handoff
    bus = getattr(service, "event_bus", None)
    if handoff.enabled and bus is not None:
        bus.subscribe("job.applied", handoff.on_applied)


async def start_phase9_services(service: Any, worker: Any, env: dict[str, str], stop: asyncio.Event, *,
                                watchers: bool = True, telegram: bool = True, client: Any = None) -> Phase9Services:
    out = Phase9Services()
    steps: list[tuple[str, Callable[[], None]]] = [
        ("profile_sync", lambda: _start_profile_sync(service, worker, out)),
        ("outreach_drafts", lambda: _start_outreach(service, worker, env)),
    ]
    if telegram:
        steps.append(("notification_router", lambda: _start_notifier(service, worker, env, out, client)))
    if watchers:
        steps.append(("watchers", lambda: _start_watchers(service, worker, stop, out)))
    for name, start in steps:
        try:
            start()
        except Exception as exc:  # noqa: BLE001 - optional services never stop the worker
            logger.warning("phase9 %s disabled for this run: %s", name, type(exc).__name__)
    return out
