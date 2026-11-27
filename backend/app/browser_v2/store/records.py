"""v2 store value objects, constants and errors (shared by MemoryStore and PostgresStore)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from backend.app.browser_v2.state import ApplicationState

HITL_STATUSES = ("OPEN", "ANSWERED", "EXPIRED", "CANCELLED")
HITL_CHANNELS = ("telegram", "dashboard", "mcp", "worker")
# Kinds whose resolved answers are handed back to the adapter on the priority re-run.
ANSWER_KINDS = ("QUESTION", "OTP", "CAPTCHA")
REF_PATTERN = re.compile(r"^[0-9a-f]{4,32}$")
TELEGRAM_STATE_FIELDS = ("last_update_id", "polling_state", "last_poll_at", "last_error",
                         "conflict_detected_at", "last_digest_on")
POLLING_STATES = ("unconfigured", "starting", "polling", "conflict", "error", "stopped")
DRAFT_STATUSES = ("PENDING", "CREATED", "FAILED")
DRAFT_CHANNELS = ("imap", "mail_app")
BODY_PREVIEW_CHARS = 280


PROFILE_KEYS = ("verified_experience_years", "verified_skills", "verified_roles", "projects", "preferences",
                "full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url", "personal_website",
                "education")


class RulesNotFound(LookupError):
    pass


class ProfileMissing(LookupError):
    pass


def validate_preferences(merged: dict[str, Any]) -> dict[str, Any]:
    """Same validation as the dashboard (JobSearchPreferences); raises ValueError when invalid."""
    from pydantic import ValidationError

    from backend.app.schemas.candidate_profile import JobSearchPreferences

    try:
        JobSearchPreferences.model_validate(merged)
    except ValidationError as exc:
        raise ValueError("invalid_preferences: " + "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])) from None
    return merged


class RevisionConflict(RuntimeError):
    def __init__(self, current: int) -> None:
        super().__init__(f"revision_conflict:current={current}")
        self.current = current


class WorkerState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


@dataclass
class WorkerControl:
    desired_state: WorkerState = WorkerState.STOPPED
    dry_run: bool = True
    run_once_requested_at: datetime | None = None
    observed_state: str = "OFFLINE"
    heartbeat_at: datetime | None = None
    current_platform: str | None = None
    last_cycle_at: datetime | None = None
    last_error: str | None = None
    revision: int = 1
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> WorkerControl:
        known = set(cls.__dataclass_fields__)
        values = {k: v for k, v in row.items() if k in known}
        values["desired_state"] = WorkerState(values.get("desired_state", "STOPPED"))
        return cls(**values)


@dataclass
class ApplicationRecord:
    id: str
    platform: str
    external_job_id: str
    state: ApplicationState
    version: int
    attempts: int = 0
    reason: str | None = None
    receipt: dict[str, Any] | None = None
    company_name: str | None = None
    role_title: str | None = None
    job_url: str | None = None
    dedup_key: str | None = None
    applied_at: datetime | None = None
    retry_after: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    draft_created_at: datetime | None = None
    # Phase 9B early-bird queue (followup 005): P0 urgent .. P3 backlog, real posting time.
    priority: int = 2
    posted_at: datetime | None = None
    posted_precision: str | None = None  # hour | day | unknown
    priority_reason: str | None = None
    discovered_via: str | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "platform": self.platform, "external_job_id": self.external_job_id,
                "company_name": self.company_name, "role_title": self.role_title,
                "job_url": self.job_url, "state": self.state.value, "reason": self.reason,
                "attempts": self.attempts, "applied_at": self.applied_at,
                "retry_after": self.retry_after, "draft_created_at": self.draft_created_at,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "priority": self.priority, "posted_at": self.posted_at,
                "posted_precision": self.posted_precision, "priority_reason": self.priority_reason,
                "discovered_via": self.discovered_via}


@dataclass
class EmailDraftRecord:
    """One public.email_drafts row (+ the linked application's display/retry fields)."""
    id: str
    application_id: str | None
    status: str
    platform: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    body_preview: str | None = None
    channel: str | None = None
    composer: str | None = None
    enrichment_source: str | None = None
    external_draft_id: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    company_name: str | None = None
    role_title: str | None = None
    application_state: str | None = None
    retry_after: datetime | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "application_id": self.application_id, "platform": self.platform,
                "company_name": self.company_name, "role_title": self.role_title,
                "recipient_email": self.recipient_email, "subject": self.subject,
                "body_preview": self.body_preview, "channel": self.channel, "status": self.status,
                "composer": self.composer, "enrichment_source": self.enrichment_source,
                "last_error": self.last_error, "created_at": self.created_at,
                "application_state": self.application_state, "retry_after": self.retry_after}


@dataclass(frozen=True)
class DraftReservation:
    """`reserved=True`: this caller owns a fresh PENDING row and may create the draft.
    Otherwise `existing` is the row that already blocks a second draft (never duplicate)."""
    reserved: bool
    draft: EmailDraftRecord | None


def _clip(value: str | None, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else value


@dataclass
class HitlRecord:
    """One public.hitl_requests row plus the linked application's display fields."""
    id: str
    platform: str
    kind: str
    prompt_text: str
    status: str = "OPEN"
    application_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    telegram_msg_id: int | None = None
    answer_text: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_via: str | None = None
    consumed_at: datetime | None = None
    company_name: str | None = None
    role_title: str | None = None
    job_url: str | None = None
    application_state: str | None = None

    @property
    def ref(self) -> str:
        """Short human reference: first 6 hex chars of the UUID (e.g. a1b2c3)."""
        return hitl_ref(self.id)

    @property
    def options(self) -> tuple[str, ...]:
        raw = self.context.get("options") or ()
        return tuple(str(o) for o in raw if str(o).strip()) if isinstance(raw, (list, tuple)) else ()

    def _nested(self, key: str) -> Any:
        inner = self.context.get("context")
        return self.context.get(key) or (inner.get(key) if isinstance(inner, dict) else None)

    @property
    def company(self) -> str | None:
        return self.company_name or self._nested("company")

    @property
    def title(self) -> str | None:
        return self.role_title or self._nested("title")

    @property
    def url(self) -> str | None:
        return self.job_url or self._nested("url")

    @property
    def resolver_reason(self) -> str | None:
        value = self._nested("resolver_reason")
        return str(value) if value else None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "ref": self.ref, "application_id": self.application_id,
                "platform": self.platform, "kind": self.kind, "status": self.status,
                "question": self.prompt_text, "options": list(self.options),
                "resolver_reason": self.resolver_reason, "company": self.company, "title": self.title,
                "job_url": self.url, "application_state": self.application_state,
                "telegram_msg_id": self.telegram_msg_id, "answer_text": self.answer_text,
                "resolved_via": self.resolved_via, "created_at": self.created_at,
                "resolved_at": self.resolved_at, "consumed_at": self.consumed_at}


def hitl_ref(hitl_id: str) -> str:
    return str(hitl_id).replace("-", "").lower()[:6]


@dataclass
class TelegramState:
    last_update_id: int | None = None
    polling_state: str = "stopped"
    last_poll_at: datetime | None = None
    last_error: str | None = None
    conflict_detected_at: datetime | None = None
    updated_at: datetime | None = None
    last_digest_on: date | None = None  # Phase 6A: nightly digest sent for this local date

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TelegramState:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in row.items() if k in known})


def _telegram_changes(changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(TELEGRAM_STATE_FIELDS)
    if unknown:
        raise ValueError(f"unknown telegram state fields: {sorted(unknown)}")
    if "polling_state" in changes and changes["polling_state"] not in POLLING_STATES:
        raise ValueError("invalid polling_state")
    if changes.get("last_error"):
        changes = changes | {"last_error": str(changes["last_error"])[:500]}
    return changes


@dataclass(frozen=True)
class ApplicationQuery:
    platform: str | None = None
    state: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    offset: int = 0


def _now() -> datetime:
    return datetime.now(UTC)
