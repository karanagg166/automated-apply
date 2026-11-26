"""MemoryStore portal circuit breaker, fresh-sweep clock and watcher state (mixin; mirrors the SQL)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.phase9_records import WatcherState, circuit_values
from backend.app.browser_v2.store.records import _now


class MemoryWatcherMixin(MemoryBase):
    async def record_circuit(self, platform: str, *, failures: int, level: int,
                             open_until: datetime | None, reason: str | None) -> None:
        failures, level, reason = circuit_values(failures, level, reason)
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], circuit_failures=failures, circuit_level=level,
                                           circuit_open_until=open_until, circuit_reason=reason)

    async def record_fresh_sweep(self, platform: str, at: datetime) -> None:
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], last_fresh_sweep_at=at)

    async def get_watcher_state(self, source: str) -> WatcherState | None:
        return self.watchers.get(source)

    async def save_watcher_state(self, state: WatcherState) -> WatcherState:
        self.watchers[state.source] = replace(state, updated_at=_now())
        return self.watchers[state.source]

    async def phase9_ready(self) -> bool:
        return True
