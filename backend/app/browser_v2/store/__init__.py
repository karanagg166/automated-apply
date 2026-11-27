"""Persistence for v2 rules, worker control and the application state machine.

PostgresStore keeps a single asyncpg connection (the Supabase runtime role has
a 5-connection cap). The API borrows the raw asyncpg connection behind its
SQLAlchemy pool session (`PostgresStore.borrowed`) instead of opening another.
MemoryStore has the same contract for tests and for dry runs before
migration 004 is applied.

Phase 4: the Telegram HITL poller runs as a second asyncio task in the worker
process, so an owned connection is wrapped in `SerializedConnection` (one
query or transaction at a time; still a single Supabase connection).
"""

from __future__ import annotations

# Constants and private helpers stay importable from the old module path (redundant aliases = re-export).
from backend.app.browser_v2.rules import dedup_key
from backend.app.browser_v2.store.agent_records import (
    FENCED_STATES,
    AuditEntry,
    ConversationTurn,
    FencedRowError,
    agent_chat_key,
)
from backend.app.browser_v2.store.base import SerializedConnection
from backend.app.browser_v2.store.base import _draft as _draft
from backend.app.browser_v2.store.base import _hitl as _hitl
from backend.app.browser_v2.store.base import _json as _json
from backend.app.browser_v2.store.base import _record as _record
from backend.app.browser_v2.store.base import _uuid as _uuid
from backend.app.browser_v2.store.memory_store import MemoryStore
from backend.app.browser_v2.store.notify_records import DigestItem, LedgerEntry
from backend.app.browser_v2.store.phase9_records import (
    SEEN_IDS_CAP,
    DiscoveryMeta,
    DiscoveryResult,
    WatcherState,
)
from backend.app.browser_v2.store.postgres import PostgresStore
from backend.app.browser_v2.store.protocol import Store
from backend.app.browser_v2.store.records import ANSWER_KINDS as ANSWER_KINDS
from backend.app.browser_v2.store.records import (
    BODY_PREVIEW_CHARS as BODY_PREVIEW_CHARS,
)
from backend.app.browser_v2.store.records import DRAFT_CHANNELS as DRAFT_CHANNELS
from backend.app.browser_v2.store.records import DRAFT_STATUSES as DRAFT_STATUSES
from backend.app.browser_v2.store.records import HITL_CHANNELS as HITL_CHANNELS
from backend.app.browser_v2.store.records import HITL_STATUSES as HITL_STATUSES
from backend.app.browser_v2.store.records import POLLING_STATES as POLLING_STATES
from backend.app.browser_v2.store.records import PROFILE_KEYS as PROFILE_KEYS
from backend.app.browser_v2.store.records import REF_PATTERN as REF_PATTERN
from backend.app.browser_v2.store.records import (
    TELEGRAM_STATE_FIELDS as TELEGRAM_STATE_FIELDS,
)
from backend.app.browser_v2.store.records import (
    ApplicationQuery,
    ApplicationRecord,
    DraftReservation,
    EmailDraftRecord,
    HitlRecord,
    ProfileMissing,
    RevisionConflict,
    RulesNotFound,
    TelegramState,
    WorkerControl,
    WorkerState,
    validate_preferences,
)
from backend.app.browser_v2.store.records import _clip as _clip
from backend.app.browser_v2.store.records import _now as _now
from backend.app.browser_v2.store.records import _telegram_changes as _telegram_changes
from backend.app.browser_v2.store.records import hitl_ref as hitl_ref

__all__ = [
    "DigestItem",
    "LedgerEntry",
    "FENCED_STATES",
    "SEEN_IDS_CAP",
    "ApplicationQuery",
    "ApplicationRecord",
    "AuditEntry",
    "ConversationTurn",
    "DiscoveryMeta",
    "DiscoveryResult",
    "DraftReservation",
    "EmailDraftRecord",
    "FencedRowError",
    "HitlRecord",
    "MemoryStore",
    "PostgresStore",
    "ProfileMissing",
    "RevisionConflict",
    "RulesNotFound",
    "SerializedConnection",
    "Store",
    "TelegramState",
    "WatcherState",
    "WorkerControl",
    "WorkerState",
    "agent_chat_key",
    "dedup_key",
    "validate_preferences",
]
