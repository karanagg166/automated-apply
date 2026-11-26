"""Phase 9C store value objects: agent audit log rows, conversation turns, the analytics funnel
and the never-replay fence (followup 005). Validation mirrors the SQL CHECK constraints so the
MemoryStore and PostgresStore accept and refuse exactly the same values."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

AUDIT_SOURCES = ("telegram", "api", "mcp", "cli", "worker")
AUDIT_OUTCOMES = ("ok", "refused", "error", "needs_confirmation", "cancelled")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
CHAT_KEY = re.compile(r"^[a-z]{2,12}:[0-9a-f]{8,64}$")
TURN_ROLES = ("user", "assistant")
MAX_TURN_CHARS = 4000
MAX_AUDIT_ERROR_CHARS = 500
TURNS_PER_CHAT = 200
# Never-replay fence: a possibly-submitted application is never modified, re-queued or re-tiered.
FENCED_STATES = ("APPLIED", "SUBMISSION_UNKNOWN")
FUNNEL_KEYS = ("discovered", "filtered", "applied", "failed", "waiting", "quota", "submission_unknown",
               "recruiter_replies")
# Current state -> funnel bucket (counted when the row was touched inside the window).
STATE_BUCKETS = {"FILTERED_OUT": "filtered", "FAILED": "failed", "WAITING_FOR_USER": "waiting",
                 "QUOTA_HIT_PENDING": "quota", "DRAFTED_AND_QUEUED": "quota",
                 "SUBMISSION_UNKNOWN": "submission_unknown"}
REPLY_KINDS = ("RECRUITER_REPLY", "INTERVIEW")


class FencedRowError(PermissionError):
    """The target application is APPLIED or SUBMISSION_UNKNOWN: it may already have been submitted."""

    def __init__(self, state: str) -> None:
        super().__init__(f"never_replay_fence:{state}")
        self.state = state


def agent_chat_key(channel: str, chat_id: Any) -> str:
    """Non-reversible conversation key, e.g. 'telegram:<sha256(chat_id)[:16]>' (never the raw id)."""
    if not re.fullmatch(r"[a-z]{2,12}", channel or ""):
        raise ValueError("invalid chat channel")
    return f"{channel}:{hashlib.sha256(str(chat_id).encode()).hexdigest()[:16]}"


def _json_object(value: Any, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a JSON object")
    json.dumps(value, default=str)  # must serialize
    return value


@dataclass(frozen=True)
class AuditEntry:
    """One public.agent_audit_log row (sanitized summaries only: no secrets, OTPs or raw PII)."""

    source: str
    tool_name: str
    outcome: str
    args: dict[str, Any] = field(default_factory=dict)
    before_summary: dict[str, Any] | None = None
    after_summary: dict[str, Any] | None = None
    error: str | None = None
    id: str | None = None
    created_at: datetime | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.source not in AUDIT_SOURCES:
            raise ValueError("invalid audit source")
        if not TOOL_NAME.match(self.tool_name or ""):
            raise ValueError("invalid audit tool_name")
        if self.outcome not in AUDIT_OUTCOMES:
            raise ValueError("invalid audit outcome")
        object.__setattr__(self, "args", _json_object(self.args or {}, "args"))
        _json_object(self.before_summary, "before_summary")
        _json_object(self.after_summary, "after_summary")
        if self.error is not None:
            object.__setattr__(self, "error", str(self.error)[:MAX_AUDIT_ERROR_CHARS])

    @classmethod
    def from_row(cls, row: Any) -> AuditEntry:
        data = dict(row)

        def load(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value

        return cls(source=data["source"], tool_name=data["tool_name"], outcome=data["outcome"],
                   args=load(data.get("args")) or {}, before_summary=load(data.get("before_summary")),
                   after_summary=load(data.get("after_summary")), error=data.get("error"),
                   id=str(data["id"]) if data.get("id") is not None else None, created_at=data.get("created_at"))

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "tool_name": self.tool_name, "outcome": self.outcome,
                "args": self.args, "before": self.before_summary, "after": self.after_summary,
                "error": self.error, "created_at": self.created_at}


@dataclass(frozen=True)
class ConversationTurn:
    """One public.agent_conversation_turns row. Content is clipped to 4000 characters."""

    chat_key: str
    role: str
    content: str
    id: str | None = None
    created_at: datetime | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not CHAT_KEY.match(self.chat_key or ""):
            raise ValueError("invalid chat_key")
        if self.role not in TURN_ROLES:
            raise ValueError("invalid turn role")
        content = (self.content or "").strip()[:MAX_TURN_CHARS]
        if not content:
            raise ValueError("empty turn content")
        object.__setattr__(self, "content", content)

    @classmethod
    def from_row(cls, row: Any) -> ConversationTurn:
        data = dict(row)
        return cls(chat_key=data["chat_key"], role=data["role"], content=data["content"],
                   id=str(data["id"]) if data.get("id") is not None else None, created_at=data.get("created_at"))


def empty_funnel() -> dict[str, int]:
    return dict.fromkeys(FUNNEL_KEYS, 0)


def check_turn_limit(limit: int) -> int:
    return max(1, min(int(limit), TURNS_PER_CHAT))
