"""Phase 9: the worker process wires profile sync, the early-bird notifier and watchers fail-soft."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from backend.app.browser_v2.store import MemoryStore
from backend.app.browser_v2.worker.wiring import start_phase9_services


class FakeBus:
    def __init__(self) -> None:
        self.subscriptions: list[str] = []

    def subscribe(self, topic: str, handler: Any) -> None:
        self.subscriptions.append(topic)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        return None


async def test_wiring_sets_profile_sync_and_subscribes_without_watchers() -> None:
    bus = FakeBus()
    service = SimpleNamespace(store=MemoryStore(), manager=SimpleNamespace(), adapters={}, env_profile={},
                              event_bus=bus)
    worker = SimpleNamespace(profile_sync=None, wake=lambda reason: None)
    stop = asyncio.Event()
    services = await start_phase9_services(service, worker, {}, stop, watchers=False, telegram=True)
    assert worker.profile_sync is services.profile_sync is not None
    assert "profile.updated" in bus.subscriptions
    assert services.tasks == []  # no watcher task, and Telegram is unconfigured -> no notifier client
    await services.aclose(stop)
    assert stop.is_set()


async def test_wiring_is_fail_soft() -> None:
    service = SimpleNamespace(store=None, manager=None, adapters=None, env_profile=None, event_bus=None)
    worker = SimpleNamespace(profile_sync=None, wake=lambda reason: None)
    stop = asyncio.Event()
    services = await start_phase9_services(service, worker, {}, stop, watchers=True, telegram=True)
    await services.aclose(stop)  # broken inputs are logged, never raised
