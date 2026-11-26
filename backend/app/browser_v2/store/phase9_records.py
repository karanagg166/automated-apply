"""Phase 9B store value objects: discovery priority metadata and fast-poll watcher state.

Shared by MemoryStore and PostgresStore (followup 005). Validation mirrors the SQL CHECK
constraints so both stores accept and refuse exactly the same values.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from backend.app.browser_v2.priority import PRECISIONS
from backend.app.browser_v2.store.records import ApplicationRecord

# Rows whose tier may still change (queued, not yet in flight or terminal).
PRIORITY_MUTABLE_STATES = ("DISCOVERED", "SCORED")
PRIORITY_REASON_CHARS = 200
CIRCUIT_REASON_CHARS = 300
CIRCUIT_MAX_LEVEL = 10
SEEN_IDS_CAP = 2000
DISCOVERED_VIA = re.compile(r"^[a-z][a-z0-9_:.-]{0,59}$")
WATCHER_SOURCE = re.compile(r"^[a-z][a-z0-9_]{1,39}(:[A-Za-z0-9_.:/-]{1,160})?$")
BODY_HASH = re.compile(r"^[0-9a-f]{64}$")


def precision_rank(precision: str | None) -> int:
    """hour (0) is better than day (1), which is better than unknown/None (2)."""
    return PRECISIONS.index(precision) if precision in PRECISIONS else len(PRECISIONS) - 1


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def check_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 3:
        raise ValueError("priority must be an int between 0 and 3")
    return priority


def circuit_values(failures: int, level: int, reason: str | None) -> tuple[int, int, str | None]:
    """Validated portal circuit-breaker values (same bounds as the portal_rules CHECKs)."""
    if failures < 0 or not 0 <= level <= CIRCUIT_MAX_LEVEL:
        raise ValueError(f"circuit failures must be >= 0 and level 0..{CIRCUIT_MAX_LEVEL}")
    return int(failures), int(level), reason[:CIRCUIT_REASON_CHARS] if reason else None


@dataclass(frozen=True)
class DiscoveryMeta:
    """How a listing was found: requested tier (None = keep/default P2) and posting time."""

    priority: int | None = None
    priority_reason: str | None = None
    posted_at: datetime | None = None
    posted_precision: str | None = None  # hour | day | unknown
    discovered_via: str | None = None

    def __post_init__(self) -> None:
        if self.priority is not None:
            check_priority(self.priority)
        if self.posted_precision is not None and self.posted_precision not in PRECISIONS:
            raise ValueError(f"posted_precision must be one of {PRECISIONS}")
        if self.discovered_via is not None and not DISCOVERED_VIA.match(self.discovered_via):
            raise ValueError("invalid discovered_via")
        if self.priority_reason is not None:
            object.__setattr__(self, "priority_reason", self.priority_reason[:PRIORITY_REASON_CHARS])
        object.__setattr__(self, "posted_at", aware(self.posted_at))
        if self.posted_at is not None and self.posted_precision is None:
            object.__setattr__(self, "posted_precision", "unknown")


@dataclass(frozen=True)
class DiscoveryResult:
    record: ApplicationRecord
    inserted: bool
    promoted: bool  # an existing queued row moved to a more urgent tier


def _clip(value: str | None, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else value


@dataclass(frozen=True)
class WatcherState:
    """One public.watcher_state row. ``seen_ids`` runs oldest -> newest, capped to the newest 2000."""

    source: str
    etag: str | None = None
    last_modified: str | None = None
    body_hash: str | None = None
    seen_ids: tuple[str, ...] = ()
    baseline_at: datetime | None = None
    last_poll_at: datetime | None = None
    next_poll_at: datetime | None = None
    last_status: int | None = None
    failures: int = 0
    open_until: datetime | None = None
    last_error: str | None = None
    budget_day: date | None = None
    budget_used: int = 0
    updated_at: datetime | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not WATCHER_SOURCE.match(self.source or ""):
            raise ValueError("invalid watcher source")
        if self.body_hash is not None and not BODY_HASH.match(self.body_hash):
            raise ValueError("body_hash must be a lowercase sha256 hex digest")
        if self.failures < 0 or self.budget_used < 0:
            raise ValueError("failures and budget_used must be >= 0")
        ids: list[str] = []
        seen: set[str] = set()
        for item in reversed([str(i) for i in self.seen_ids]):  # keep the newest occurrence
            if item not in seen:
                seen.add(item)
                ids.append(item)
        object.__setattr__(self, "seen_ids", tuple(reversed(ids[:SEEN_IDS_CAP])))
        object.__setattr__(self, "etag", _clip(self.etag, 300))
        object.__setattr__(self, "last_modified", _clip(self.last_modified, 100))
        object.__setattr__(self, "last_error", _clip(self.last_error, 500))
        for name in ("baseline_at", "last_poll_at", "next_poll_at", "open_until"):
            object.__setattr__(self, name, aware(getattr(self, name)))

    def with_seen(self, ids: list[str] | tuple[str, ...]) -> WatcherState:
        """Append newly seen ids (newest last); the cap drops the oldest."""
        return replace(self, seen_ids=(*self.seen_ids, *ids))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> WatcherState:
        data = dict(row)
        raw = data.get("seen_ids")
        seen = json.loads(raw) if isinstance(raw, str) else (raw or [])
        known = set(cls.__dataclass_fields__)
        values = {k: v for k, v in data.items() if k in known and k != "seen_ids"}
        values["failures"] = values.get("failures") or 0
        values["budget_used"] = values.get("budget_used") or 0
        return cls(**values, seen_ids=tuple(str(i) for i in seen) if isinstance(seen, list) else ())
