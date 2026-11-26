"""MemoryStore agent audit log, conversation memory, analytics funnel and fenced owner queue
(mixin; mirrors AuditRepo / ConversationRepo / AnalyticsRepo / OwnerQueueRepo)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.store.agent_records import (
    CHAT_KEY,
    FENCED_STATES,
    STATE_BUCKETS,
    TURNS_PER_CHAT,
    AuditEntry,
    ConversationTurn,
    FencedRowError,
    check_turn_limit,
    empty_funnel,
)
from backend.app.browser_v2.store.analytics_repo import funnel_since
from backend.app.browser_v2.store.memory_priority import MemoryPriorityMixin
from backend.app.browser_v2.store.phase9_records import (
    PRIORITY_REASON_CHARS,
    DiscoveryMeta,
    DiscoveryResult,
    check_priority,
)


class MemoryAgentMixin(MemoryPriorityMixin):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_audit: list[AuditEntry] = []
        self.agent_turns: list[ConversationTurn] = []

    # --- audit (append-only) ----------------------------------------------------------------
    async def append_audit(self, entry: AuditEntry) -> AuditEntry:
        stored = replace(entry, id=str(uuid.uuid4()), created_at=datetime.now(UTC))
        self.agent_audit.append(stored)
        return stored

    async def list_audit(self, limit: int = 20, tool_name: str | None = None) -> list[AuditEntry]:
        rows = [e for e in reversed(self.agent_audit) if tool_name is None or e.tool_name == tool_name]
        return rows[:max(1, min(int(limit), 200))]

    # --- conversation memory ------------------------------------------------------------------
    async def append_turn(self, turn: ConversationTurn) -> None:
        self.agent_turns.append(replace(turn, id=str(uuid.uuid4()), created_at=datetime.now(UTC)))
        mine = [t for t in self.agent_turns if t.chat_key == turn.chat_key]
        if len(mine) > TURNS_PER_CHAT:
            drop = {id(t) for t in mine[:len(mine) - TURNS_PER_CHAT]}
            self.agent_turns = [t for t in self.agent_turns if id(t) not in drop]

    async def recent_turns(self, chat_key: str, limit: int = 12) -> list[ConversationTurn]:
        if not CHAT_KEY.match(chat_key or ""):
            return []
        mine = [t for t in self.agent_turns if t.chat_key == chat_key]
        return mine[-check_turn_limit(limit):]

    async def clear_turns(self, chat_key: str) -> int:
        before = len(self.agent_turns)
        self.agent_turns = [t for t in self.agent_turns if t.chat_key != chat_key]
        return before - len(self.agent_turns)

    # --- analytics ----------------------------------------------------------------------------
    async def funnel(self, days: int = 7, platform: str | None = None, *,
                     now: datetime | None = None) -> dict[str, dict[str, int]]:
        """Applications only (recruiter replies live in MailEventStore: always 0 here)."""
        since = funnel_since(days, now)
        out: dict[str, dict[str, int]] = {}
        for record in self.records.values():
            if platform is not None and record.platform != platform:
                continue
            created = record.created_at is not None and record.created_at >= since
            touched = record.updated_at is not None and record.updated_at >= since
            applied = record.applied_at is not None and record.applied_at >= since
            if not (created or touched or applied):
                continue
            bucket = out.setdefault(record.platform, empty_funnel())
            bucket["discovered"] += int(created)
            bucket["applied"] += int(record.state.value == "APPLIED" and applied)
            name = STATE_BUCKETS.get(record.state.value)
            if name is not None and touched:
                bucket[name] += 1
        return out

    # --- owner queue (never-replay fence enforced here) -------------------------------------------
    async def enqueue_owner_job(self, listing: JobListing, meta: DiscoveryMeta) -> DiscoveryResult:
        current = self.records.get((listing.platform, listing.external_job_id))
        if current is not None and current.state.value in FENCED_STATES:
            raise FencedRowError(current.state.value)
        return await self.upsert_discovered_meta(listing, meta)

    async def set_owner_priority(self, application_id: str, priority: int, reason: str | None) -> bool:
        check_priority(priority)
        for record in self.records.values():
            if record.id == application_id:
                if record.state.value in FENCED_STATES:
                    raise FencedRowError(record.state.value)
                record.priority = priority
                record.priority_reason = reason[:PRIORITY_REASON_CHARS] if reason else None
                return True
        return False
