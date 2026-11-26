"""MemoryStore in-memory state (shared by the MemoryStore mixins)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.browser_v2.rules import DEFAULT_RULES, PortalRules
from backend.app.browser_v2.store.phase9_records import WatcherState
from backend.app.browser_v2.store.records import (
    ApplicationRecord,
    TelegramState,
    WorkerControl,
)


class MemoryBase:
    def __init__(self, rules: dict[str, PortalRules] | None = None,
                 profile: dict[str, Any] | None = None,
                 worker: WorkerControl | None = None) -> None:
        self.rules = dict(rules or DEFAULT_RULES)
        self.records: dict[tuple[str, str], ApplicationRecord] = {}
        self.events: list[dict[str, Any]] = []
        self.auth: dict[str, str] = {}
        self.profile = profile or {}
        self.applied_at: list[tuple[str, datetime]] = []
        self.hitl: list[dict[str, Any]] = []
        self.worker = worker or WorkerControl()
        self.heartbeats: list[str] = []
        self.telegram = TelegramState()
        self.drafts: list[dict[str, Any]] = []
        self.watchers: dict[str, WatcherState] = {}  # Phase 9B fast-poll watcher state
