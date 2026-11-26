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

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.answers import normalize
from backend.app.browser_v2.rules import (
    ALL_EDITABLE_RULE_FIELDS,
    DEFAULT_RULES,
    EDITABLE_RULE_FIELDS,
    OVERRIDE_RULE_FIELDS,
    PortalRules,
    apply_overrides,
    dedup_key,
)
from backend.app.browser_v2.state import (
    ApplicationState,
    InvalidTransition,
    check_transition,
)

__all__ = [
    "ApplicationQuery",
    "ApplicationRecord",
    "DraftReservation",
    "EmailDraftRecord",
    "HitlRecord",
    "MemoryStore",
    "PostgresStore",
    "ProfileMissing",
    "RevisionConflict",
    "RulesNotFound",
    "SerializedConnection",
    "Store",
    "TelegramState",
    "WorkerControl",
    "WorkerState",
    "dedup_key",
    "validate_preferences",
]

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
                "full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url", "personal_website")


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

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "platform": self.platform, "external_job_id": self.external_job_id,
                "company_name": self.company_name, "role_title": self.role_title,
                "job_url": self.job_url, "state": self.state.value, "reason": self.reason,
                "attempts": self.attempts, "applied_at": self.applied_at,
                "retry_after": self.retry_after, "draft_created_at": self.draft_created_at,
                "created_at": self.created_at, "updated_at": self.updated_at}


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


class Store(Protocol):
    async def get_rules(self, platform: str) -> PortalRules: ...

    async def list_rules(self) -> list[PortalRules]: ...

    async def update_rules(self, platform: str, changes: dict[str, Any],
                           expected_revision: int) -> PortalRules: ...

    async def get(self, platform: str, external_job_id: str) -> ApplicationRecord | None: ...

    async def upsert_discovered(self, listing: JobListing) -> ApplicationRecord: ...

    async def get_application(self, application_id: str) -> ApplicationRecord | None: ...

    async def transition(self, record: ApplicationRecord, target: ApplicationState, reason: str, *,
                         receipt: dict[str, Any] | None = None, payload: dict[str, Any] | None = None,
                         count_attempt: bool = False,
                         retry_after: datetime | None = None) -> ApplicationRecord: ...

    async def find_duplicates(self, key: str, *, platform: str,
                              external_job_id: str) -> list[ApplicationRecord]: ...

    async def list_by_state(self, platform: str, states: tuple[ApplicationState, ...],
                            limit: int = 50) -> list[ApplicationRecord]: ...

    async def record_auth(self, platform: str, status: str) -> None: ...

    async def record_portal_limit(self, platform: str) -> None: ...

    async def create_hitl(self, record: ApplicationRecord | None, platform: str, kind: str,
                          prompt: str, context: dict[str, Any]) -> str: ...

    async def open_hitl_exists(self, platform: str, kind: str) -> bool: ...

    async def cancel_open_hitl(self, platform: str, kind: str) -> int: ...

    # --- Phase 4 HITL inbox (Telegram + dashboard) ---
    async def get_hitl(self, hitl_id: str) -> HitlRecord | None: ...

    async def find_open_hitl_by_ref(self, ref: str) -> list[HitlRecord]: ...

    async def find_hitl_by_message(self, message_id: int) -> HitlRecord | None: ...

    async def list_hitl(self, status: str | None = "OPEN", platform: str | None = None,
                        limit: int = 50, offset: int = 0) -> tuple[list[HitlRecord], int]: ...

    async def undelivered_hitl(self, limit: int = 10) -> list[HitlRecord]: ...

    async def mark_hitl_delivered(self, hitl_id: str, message_id: int) -> None: ...

    async def close_hitl(self, hitl_id: str, status: str, answer_text: str | None,
                         via: str) -> HitlRecord | None: ...

    async def count_open_hitl(self, platform: str | None = None) -> int: ...

    async def expire_stale_hitl(self, kind: str, older_than: datetime) -> list[HitlRecord]: ...

    async def claim_digest_day(self, day: date) -> bool: ...

    async def release_digest_day(self, day: date, previous: date | None) -> None: ...

    async def requeued_applications(self, platform: str, limit: int = 20) -> list[ApplicationRecord]: ...

    async def hitl_answers(self, application_id: str) -> dict[str, str]: ...

    async def mark_hitl_consumed(self, application_id: str) -> int: ...

    async def get_telegram_state(self) -> TelegramState: ...

    async def update_telegram_state(self, **changes: Any) -> TelegramState: ...

    async def count_state(self, state: ApplicationState, platform: str | None = None) -> int: ...

    # --- Phase 5: quota-hit drafts + next-day retry ---
    async def due_retries(self, platform: str, now: datetime, limit: int = 20) -> list[ApplicationRecord]: ...

    async def parked_since(self, platform: str, since: datetime) -> int: ...

    async def reserve_email_draft(self, application_id: str, platform: str | None,
                                  recipient_email: str | None) -> DraftReservation: ...

    async def complete_email_draft(self, draft_id: str, *, channel: str, subject: str, body_preview: str,
                                   composer: str | None, enrichment_source: str | None,
                                   external_draft_id: str | None) -> EmailDraftRecord: ...

    async def fail_email_draft(self, draft_id: str, error: str, *, ambiguous: bool = False) -> None: ...

    async def get_email_draft(self, application_id: str) -> EmailDraftRecord | None: ...

    async def list_email_drafts(self, platform: str | None = None, limit: int = 50,
                                offset: int = 0) -> tuple[list[EmailDraftRecord], int]: ...

    async def count_email_drafts(self, status: str = "CREATED", platform: str | None = None,
                                 since: datetime | None = None) -> int: ...

    async def applied_since(self, platform: str, since: datetime) -> int: ...

    async def list_applications(self, query: ApplicationQuery) -> tuple[list[ApplicationRecord], int]: ...

    async def application_events(self, application_id: str) -> list[dict[str, Any]] | None: ...

    async def load_profile(self) -> tuple[dict[str, Any], list[tuple[str, str]]]: ...

    async def update_preferences(self, changes: dict[str, Any]) -> dict[str, Any]: ...

    async def get_worker_control(self) -> WorkerControl: ...

    async def set_worker_control(self, desired_state: WorkerState | None = None, *,
                                 dry_run: bool | None = None,
                                 run_once: bool = False) -> WorkerControl: ...

    async def worker_heartbeat(self, observed_state: str, *, current_platform: str | None = None,
                               last_error: str | None = None, cycle_completed: bool = False,
                               clear_run_once: bool = False) -> None: ...

    async def close(self) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
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

    async def get_rules(self, platform: str) -> PortalRules:
        return self.rules.get(platform, PortalRules(platform=platform))

    async def list_rules(self) -> list[PortalRules]:
        return [self.rules[k] for k in sorted(self.rules)]

    async def update_rules(self, platform, changes, expected_revision):
        current = self.rules.get(platform)
        if current is None:
            raise RulesNotFound(platform)
        if current.revision != expected_revision:
            raise RevisionConflict(current.revision)
        allowed = {k: v for k, v in changes.items() if k in ALL_EDITABLE_RULE_FIELDS}
        self.rules[platform] = replace(current, **allowed, revision=current.revision + 1,
                                       updated_at=_now())
        return self.rules[platform]

    async def get(self, platform: str, external_job_id: str) -> ApplicationRecord | None:
        record = self.records.get((platform, external_job_id))
        return replace(record) if record else None

    async def upsert_discovered(self, listing: JobListing) -> ApplicationRecord:
        key = (listing.platform, listing.external_job_id)
        if key not in self.records:
            self.records[key] = ApplicationRecord(
                id=f"mem-{len(self.records) + 1}", platform=listing.platform,
                external_job_id=listing.external_job_id, state=ApplicationState.DISCOVERED, version=1,
                company_name=listing.company, role_title=listing.title, job_url=listing.url,
                dedup_key=dedup_key(listing.company, listing.title), created_at=_now(),
                updated_at=_now())
        else:
            current = self.records[key]
            current.company_name = current.company_name or listing.company
            current.role_title = current.role_title or listing.title
            current.dedup_key = current.dedup_key or dedup_key(listing.company, listing.title)
        return replace(self.records[key])

    async def get_application(self, application_id):
        for record in self.records.values():
            if record.id == application_id:
                return replace(record)
        return None

    async def transition(self, record, target, reason, *, receipt=None, payload=None,
                         count_attempt=False, retry_after=None):
        current = self.records[(record.platform, record.external_job_id)]
        if current.version != record.version:
            raise InvalidTransition("stale_version")
        check_transition(current.state, target)
        self.events.append({"application_id": current.id, "from": current.state, "to": target,
                            "reason": reason, "payload": payload or {}, "created_at": _now()})
        current.state, current.reason = ApplicationState(target), reason
        current.version += 1
        current.attempts += int(count_attempt)
        current.updated_at = _now()
        if receipt is not None:
            current.receipt = receipt
        if retry_after is not None:
            current.retry_after = retry_after
        if target == ApplicationState.APPLIED:
            current.applied_at = _now()
            self.applied_at.append((record.platform, current.applied_at))
        return replace(current)

    async def find_duplicates(self, key, *, platform, external_job_id):
        return [replace(r) for (p, e), r in self.records.items()
                if r.dedup_key == key and (p, e) != (platform, external_job_id)]

    async def list_by_state(self, platform, states, limit=50):
        rows = [replace(r) for (p, _), r in self.records.items() if p == platform and r.state in states]
        return rows[:limit]

    async def record_auth(self, platform: str, status: str) -> None:
        self.auth[platform] = status
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], auth_status=status,
                                           auth_checked_at=_now())

    async def record_portal_limit(self, platform: str) -> None:
        if platform in self.rules:
            self.rules[platform] = replace(self.rules[platform], portal_limit_hit_at=_now())

    async def create_hitl(self, record, platform, kind, prompt, context):
        hitl_id = str(uuid.uuid4())
        self.hitl.append({"id": hitl_id, "application_id": record.id if record else None,
                          "platform": platform, "kind": kind, "prompt": prompt, "context": context,
                          "status": "OPEN", "telegram_msg_id": None, "answer_text": None,
                          "created_at": _now(), "resolved_at": None, "resolved_via": None,
                          "consumed_at": None})
        return hitl_id

    def _hitl_record(self, row: dict[str, Any]) -> HitlRecord:
        app = next((r for r in self.records.values() if r.id == row.get("application_id")), None)
        return HitlRecord(
            id=row["id"], platform=row["platform"], kind=row["kind"], prompt_text=row["prompt"],
            status=row["status"], application_id=row.get("application_id"),
            context=dict(row.get("context") or {}), telegram_msg_id=row.get("telegram_msg_id"),
            answer_text=row.get("answer_text"), created_at=row.get("created_at"),
            resolved_at=row.get("resolved_at"), resolved_via=row.get("resolved_via"),
            consumed_at=row.get("consumed_at"), company_name=app.company_name if app else None,
            role_title=app.role_title if app else None, job_url=app.job_url if app else None,
            application_state=app.state.value if app else None)

    async def get_hitl(self, hitl_id):
        row = next((h for h in self.hitl if h.get("id") == hitl_id), None)
        return self._hitl_record(row) if row else None

    async def find_open_hitl_by_ref(self, ref):
        ref = (ref or "").lower().replace("-", "")
        if not REF_PATTERN.match(ref):
            return []
        return [self._hitl_record(h) for h in self.hitl
                if h["status"] == "OPEN" and h["id"].replace("-", "").startswith(ref)]

    async def find_hitl_by_message(self, message_id):
        row = next((h for h in self.hitl if h.get("telegram_msg_id") == message_id), None)
        return self._hitl_record(row) if row else None

    async def list_hitl(self, status="OPEN", platform=None, limit=50, offset=0):
        rows = [h for h in self.hitl if (status is None or h["status"] == status)
                and (platform is None or h["platform"] == platform)]
        rows.sort(key=lambda h: h["created_at"])
        return [self._hitl_record(h) for h in rows[offset: offset + limit]], len(rows)

    async def undelivered_hitl(self, limit=10):
        rows = [h for h in self.hitl if h["status"] == "OPEN" and h.get("telegram_msg_id") is None]
        return [self._hitl_record(h) for h in sorted(rows, key=lambda h: h["created_at"])[:limit]]

    async def mark_hitl_delivered(self, hitl_id, message_id):
        for row in self.hitl:
            if row.get("id") == hitl_id and row.get("telegram_msg_id") is None:
                row["telegram_msg_id"] = message_id

    async def close_hitl(self, hitl_id, status, answer_text, via):
        row = next((h for h in self.hitl if h.get("id") == hitl_id), None)
        if row is None or row["status"] != "OPEN":
            return None  # already resolved elsewhere (double click / dashboard race)
        row.update(status=status, answer_text=answer_text, resolved_at=_now(), resolved_via=via)
        return self._hitl_record(row)

    async def count_open_hitl(self, platform=None):
        return sum(1 for h in self.hitl if h["status"] == "OPEN"
                   and (platform is None or h["platform"] == platform))

    async def expire_stale_hitl(self, kind, older_than):
        expired = []
        for row in self.hitl:
            if row["status"] == "OPEN" and row["kind"] == kind and row["created_at"] < older_than:
                row["status"], row["resolved_at"], row["resolved_via"] = "EXPIRED", _now(), "worker"
                expired.append(self._hitl_record(row))
        return expired

    async def claim_digest_day(self, day):
        if self.telegram.last_digest_on == day:
            return False
        self.telegram.last_digest_on = day
        return True

    async def release_digest_day(self, day, previous):
        if self.telegram.last_digest_on == day:
            self.telegram.last_digest_on = previous

    async def requeued_applications(self, platform, limit=20):
        now = _now()
        pending = {h["application_id"] for h in self.hitl
                   if h["status"] == "ANSWERED" and h.get("consumed_at") is None and h.get("application_id")}
        rows = [replace(r) for (p, _), r in self.records.items()
                if p == platform and r.state == ApplicationState.SCORED and r.id in pending
                and (r.retry_after is None or r.retry_after <= now)]
        rows.sort(key=lambda r: r.retry_after or r.updated_at or now)
        return rows[:limit]

    async def hitl_answers(self, application_id):
        rows = [h for h in self.hitl if h.get("application_id") == application_id
                and h["status"] == "ANSWERED" and h["kind"] in ANSWER_KINDS and h.get("answer_text")]
        rows.sort(key=lambda h: h["resolved_at"] or h["created_at"])
        return {h["prompt"]: h["answer_text"] for h in rows}

    async def mark_hitl_consumed(self, application_id):
        count = 0
        for row in self.hitl:
            if row.get("application_id") == application_id and row["status"] == "ANSWERED" \
                    and row.get("consumed_at") is None:
                row["consumed_at"], count = _now(), count + 1
        return count

    async def get_telegram_state(self):
        return replace(self.telegram)

    async def update_telegram_state(self, **changes):
        for key, value in _telegram_changes(changes).items():
            setattr(self.telegram, key, value)
        self.telegram.updated_at = _now()
        return replace(self.telegram)

    async def open_hitl_exists(self, platform, kind):
        return any(h["platform"] == platform and h["kind"] == kind and h["status"] == "OPEN"
                   for h in self.hitl)

    async def cancel_open_hitl(self, platform, kind):
        count = 0
        for item in self.hitl:
            if item["platform"] == platform and item["kind"] == kind and item["status"] == "OPEN":
                item["status"], count = "CANCELLED", count + 1
        return count

    async def count_state(self, state, platform=None):
        return sum(1 for (p, _), r in self.records.items()
                   if r.state == state and (platform is None or p == platform))

    async def applied_since(self, platform: str, since: datetime) -> int:
        return sum(1 for p, at in self.applied_at if p == platform and at >= since)

    async def list_applications(self, query):
        rows = [r for r in self.records.values()
                if (query.platform is None or r.platform == query.platform)
                and (query.state is None or r.state.value == query.state)
                and (query.since is None or (r.updated_at and r.updated_at >= query.since))
                and (query.until is None or (r.updated_at and r.updated_at < query.until))]
        rows.sort(key=lambda r: r.updated_at or _now(), reverse=True)
        return [replace(r) for r in rows[query.offset: query.offset + query.limit]], len(rows)

    async def application_events(self, application_id):
        if not any(r.id == application_id for r in self.records.values()):
            return None
        return [{"from_state": e["from"].value if e["from"] else None,
                 "to_state": ApplicationState(e["to"]).value, "event_type": e["reason"],
                 "payload": e["payload"], "created_at": e["created_at"]}
                for e in self.events if e["application_id"] == application_id]

    async def load_profile(self):
        return self.profile, []

    async def update_preferences(self, changes):
        if not self.profile:
            raise ProfileMissing("no_candidate_profile")
        merged = validate_preferences(dict(self.profile.get("preferences") or {}) | dict(changes))
        self.profile["preferences"] = merged
        return dict(merged)

    async def get_worker_control(self) -> WorkerControl:
        return replace(self.worker)

    async def set_worker_control(self, desired_state=None, *, dry_run=None, run_once=False):
        if desired_state is not None:
            self.worker.desired_state = WorkerState(desired_state)
        if dry_run is not None:
            self.worker.dry_run = dry_run
        if run_once:
            self.worker.run_once_requested_at = _now()
        self.worker.revision += 1
        self.worker.updated_at = _now()
        return replace(self.worker)

    async def worker_heartbeat(self, observed_state, *, current_platform=None, last_error=None,
                               cycle_completed=False, clear_run_once=False):
        self.heartbeats.append(observed_state)
        self.worker.observed_state = observed_state
        self.worker.heartbeat_at = _now()
        self.worker.current_platform = current_platform
        self.worker.last_error = last_error
        if cycle_completed:
            self.worker.last_cycle_at = _now()
        if clear_run_once:
            self.worker.run_once_requested_at = None

    # --- Phase 5 -------------------------------------------------------------------
    async def due_retries(self, platform, now, limit=20):
        rows = [replace(r) for (p, _), r in self.records.items()
                if p == platform and r.state == ApplicationState.DRAFTED_AND_QUEUED
                and r.retry_after is not None and r.retry_after <= now]
        rows.sort(key=lambda r: (r.retry_after, r.updated_at or now))
        return rows[:limit]

    async def parked_since(self, platform, since):
        ids = {r.id for (p, _), r in self.records.items() if p == platform}
        return sum(1 for e in self.events if e["application_id"] in ids
                   and ApplicationState(e["to"]) == ApplicationState.QUOTA_HIT_PENDING
                   and e["from"] != ApplicationState.QUOTA_HIT_PENDING and e["created_at"] >= since)

    def _draft_record(self, row: dict[str, Any]) -> EmailDraftRecord:
        app = next((r for r in self.records.values() if r.id == row.get("application_id")), None)
        known = set(EmailDraftRecord.__dataclass_fields__)
        values = {k: v for k, v in row.items() if k in known}
        return EmailDraftRecord(**values, company_name=app.company_name if app else None,
                                role_title=app.role_title if app else None,
                                application_state=app.state.value if app else None,
                                retry_after=app.retry_after if app else None)

    async def reserve_email_draft(self, application_id, platform, recipient_email):
        existing = next((d for d in self.drafts if d["application_id"] == application_id), None)
        if existing is not None:
            if existing["status"] != "FAILED":
                return DraftReservation(False, self._draft_record(existing))
            existing.update(status="PENDING", recipient_email=recipient_email, last_error=None,
                            updated_at=_now())  # a definite failure may be retried once more
            return DraftReservation(True, self._draft_record(existing))
        row = {"id": str(uuid.uuid4()), "application_id": application_id, "platform": platform,
               "recipient_email": recipient_email, "status": "PENDING", "created_at": _now(),
               "updated_at": _now()}
        self.drafts.append(row)
        return DraftReservation(True, self._draft_record(row))

    async def complete_email_draft(self, draft_id, *, channel, subject, body_preview, composer,
                                   enrichment_source, external_draft_id):
        if channel not in DRAFT_CHANNELS:
            raise ValueError("invalid draft channel")
        row = next(d for d in self.drafts if d["id"] == draft_id)
        row.update(status="CREATED", channel=channel, subject=subject,
                   body_preview=_clip(body_preview, BODY_PREVIEW_CHARS), composer=composer,
                   enrichment_source=enrichment_source, external_draft_id=external_draft_id,
                   last_error=None, created_at=_now(), updated_at=_now())
        for record in self.records.values():
            if record.id == row["application_id"] and record.draft_created_at is None:
                record.draft_created_at = _now()
        return self._draft_record(row)

    async def fail_email_draft(self, draft_id, error, *, ambiguous=False):
        row = next((d for d in self.drafts if d["id"] == draft_id), None)
        if row is not None:
            row.update(last_error=_clip(error, 200), updated_at=_now(),
                       status="PENDING" if ambiguous else "FAILED")

    async def get_email_draft(self, application_id):
        row = next((d for d in self.drafts if d["application_id"] == application_id), None)
        return self._draft_record(row) if row else None

    async def list_email_drafts(self, platform=None, limit=50, offset=0):
        rows = [d for d in self.drafts if platform is None or d.get("platform") == platform]
        rows.sort(key=lambda d: d["created_at"], reverse=True)
        return [self._draft_record(d) for d in rows[offset: offset + limit]], len(rows)

    async def count_email_drafts(self, status="CREATED", platform=None, since=None):
        return sum(1 for d in self.drafts if d["status"] == status
                   and (platform is None or d.get("platform") == platform)
                   and (since is None or d["created_at"] >= since))

    async def close(self) -> None:
        return None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _hitl(row: Any) -> HitlRecord:
    data = dict(row)
    context = _json(data.get("context")) or {}
    return HitlRecord(
        id=str(data["id"]), platform=data["platform"], kind=data["kind"], prompt_text=data["prompt_text"],
        status=data["status"], application_id=str(data["application_id"]) if data.get("application_id") else None,
        context=context if isinstance(context, dict) else {}, telegram_msg_id=data.get("telegram_msg_id"),
        answer_text=data.get("answer_text"), created_at=data.get("created_at"),
        resolved_at=data.get("resolved_at"), resolved_via=data.get("resolved_via"),
        consumed_at=data.get("consumed_at"), company_name=data.get("company_name"),
        role_title=data.get("role_title"), job_url=data.get("job_url"),
        application_state=data.get("application_state"))


def _uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


class SerializedConnection:
    """One asyncpg connection shared by concurrent tasks (worker loop + Telegram poller).

    asyncpg allows one in-flight operation per connection; this proxy runs one
    query or one whole transaction at a time. Re-entrant for the task that holds
    it, so statements inside `async with transaction()` do not deadlock.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None

    @asynccontextmanager
    async def _hold(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            yield
            return
        async with self._lock:
            self._owner = task
            try:
                yield
            finally:
                self._owner = None

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetch(*args, **kwargs)

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetchrow(*args, **kwargs)

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetchval(*args, **kwargs)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.execute(*args, **kwargs)

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.executemany(*args, **kwargs)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._hold(), self._connection.transaction():
            yield

    async def close(self) -> None:
        await self._connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _record(row: Any) -> ApplicationRecord:
    data = dict(row)
    return ApplicationRecord(
        id=str(data["id"]), platform=data["platform"], external_job_id=data["external_job_id"],
        state=ApplicationState(data["state"]), version=data["version"], attempts=data["attempts"],
        reason=data["reason"], receipt=_json(data.get("receipt")),
        company_name=data.get("company_name"), role_title=data.get("role_title"),
        job_url=data.get("job_url"), dedup_key=data.get("dedup_key"),
        applied_at=data.get("applied_at"), retry_after=data.get("retry_after"),
        created_at=data.get("created_at"), updated_at=data.get("updated_at"),
        draft_created_at=data.get("draft_created_at"))


def _draft(row: Any) -> EmailDraftRecord:
    data = dict(row)
    known = set(EmailDraftRecord.__dataclass_fields__)
    values = {k: v for k, v in data.items() if k in known}
    values["id"] = str(values["id"])
    values["application_id"] = str(values["application_id"]) if values.get("application_id") else None
    return EmailDraftRecord(**values)


class PostgresStore:
    COLUMNS = ("id, platform, external_job_id, state, version, attempts, reason, receipt, "
               "company_name, role_title, job_url, dedup_key, applied_at, retry_after, "
               "created_at, updated_at, draft_created_at")

    def __init__(self, connection: Any, *, owns_connection: bool = True) -> None:
        self.connection = connection
        self.owns_connection = owns_connection

    @staticmethod
    async def schema_ready(connection: Any) -> bool:
        return bool(await connection.fetchval(
            "SELECT to_regclass('public.applications') IS NOT NULL "
            "AND to_regclass('public.portal_rules') IS NOT NULL "
            "AND to_regclass('public.worker_control') IS NOT NULL"))

    @classmethod
    async def connect(cls, settings: Any) -> PostgresStore:
        import asyncpg

        from backend.app.db.safety import database_connect_args

        url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(url, **database_connect_args(settings))
        if not await cls.schema_ready(connection):
            await connection.close()
            raise RuntimeError("v2_schema_missing: run backend.scripts.migrate_v2_core apply first")
        return cls(SerializedConnection(connection))

    @classmethod
    async def borrowed(cls, connection: Any) -> PostgresStore:
        """Wrap an asyncpg connection owned by the SQLAlchemy pool (never closed here)."""
        if not await cls.schema_ready(connection):
            raise RuntimeError("v2_schema_missing")
        return cls(connection, owns_connection=False)

    # --- portal rules ---------------------------------------------------------------
    async def rule_overrides(self) -> dict[str, Any]:
        """preferences.portal_rule_overrides ({platform: {rule: value}}); {} without a profile."""
        try:
            raw = await self.connection.fetchval(
                "SELECT preferences->'portal_rule_overrides' FROM public.candidate_profiles "
                "WHERE singleton_key='primary'")
        except Exception:  # noqa: BLE001 - profile table drift must never block the rules engine
            return {}
        value = _json(raw) if raw is not None else {}
        return value if isinstance(value, dict) else {}

    async def ensure_rule_rows(self) -> None:
        """Phase 8b: seed (disabled) rows for registry portals added after migration 004, once per store.
        The runtime role has INSERT on portal_rules; ON CONFLICT keeps every owner edit."""
        if getattr(self, "_rules_seeded", False):
            return
        self._rules_seeded = True
        from backend.app.browser_v2.portals import PORTALS

        try:
            await self.connection.execute(
                "INSERT INTO public.portal_rules (platform, enabled) SELECT p, false FROM unnest($1::text[]) AS p "
                "ON CONFLICT (platform) DO NOTHING", sorted(PORTALS))
        except Exception:  # noqa: BLE001, S110 - missing grant: the registry portals simply stay unlisted
            pass

    async def get_rules(self, platform: str) -> PortalRules:
        await self.ensure_rule_rows()
        row = await self.connection.fetchrow("SELECT * FROM public.portal_rules WHERE platform=$1", platform)
        rules = PortalRules.from_row(dict(row)) if row else PortalRules(platform=platform)
        return apply_overrides(rules, await self.rule_overrides())

    async def list_rules(self) -> list[PortalRules]:
        await self.ensure_rule_rows()
        rows = await self.connection.fetch("SELECT * FROM public.portal_rules ORDER BY platform")
        overrides = await self.rule_overrides()
        return [apply_overrides(PortalRules.from_row(dict(row)), overrides) for row in rows]

    async def _save_overrides(self, platform: str, values: dict[str, Any]) -> None:
        current = await self.rule_overrides()
        entry = dict(current.get(platform) or {}) | values
        await self.update_preferences({"portal_rule_overrides": current | {platform: entry}})

    async def update_rules(self, platform, changes, expected_revision):
        overrides = {c: changes[c] for c in OVERRIDE_RULE_FIELDS if c in changes}
        if overrides:
            # Revision-checked first so a stale dashboard form never writes the override.
            current = await self.connection.fetchval(
                "SELECT revision FROM public.portal_rules WHERE platform=$1", platform)
            if current is None:
                raise RulesNotFound(platform)
            if current != expected_revision:
                raise RevisionConflict(current)
            await self._save_overrides(platform, overrides)
        columns = [c for c in EDITABLE_RULE_FIELDS if c in changes]
        values = [str(changes[c]) if c == "unknown_applicants_policy" else changes[c] for c in columns]
        assignments = "".join(f"{column}=${index + 3}, " for index, column in enumerate(columns))
        row = await self.connection.fetchrow(
            f"""UPDATE public.portal_rules SET {assignments}revision=revision + 1, updated_at=now()
                WHERE platform=$1 AND revision=$2 RETURNING *""",
            platform, expected_revision, *values)
        if row is not None:
            return apply_overrides(PortalRules.from_row(dict(row)), await self.rule_overrides())
        current = await self.connection.fetchval(
            "SELECT revision FROM public.portal_rules WHERE platform=$1", platform)
        if current is None:
            raise RulesNotFound(platform)
        raise RevisionConflict(current)

    # --- applications ---------------------------------------------------------------
    async def get(self, platform: str, external_job_id: str) -> ApplicationRecord | None:
        row = await self.connection.fetchrow(
            f"SELECT {self.COLUMNS} FROM public.applications WHERE platform=$1 AND external_job_id=$2",
            platform, external_job_id)
        return _record(row) if row else None

    async def upsert_discovered(self, listing: JobListing) -> ApplicationRecord:
        # Fill missing company/title/dedup_key on re-discovery; never touch state.
        await self.connection.execute(
            """INSERT INTO public.applications
                   (platform, external_job_id, company_name, role_title, job_url, dedup_key, state)
               VALUES ($1, $2, $3, $4, $5, $6, 'DISCOVERED')
               ON CONFLICT (platform, external_job_id) DO UPDATE SET
                   company_name=COALESCE(public.applications.company_name, EXCLUDED.company_name),
                   role_title=COALESCE(public.applications.role_title, EXCLUDED.role_title),
                   job_url=COALESCE(public.applications.job_url, EXCLUDED.job_url),
                   dedup_key=COALESCE(public.applications.dedup_key, EXCLUDED.dedup_key)
               WHERE public.applications.dedup_key IS NULL
                  OR public.applications.company_name IS NULL
                  OR public.applications.role_title IS NULL""",
            listing.platform, listing.external_job_id, listing.company, listing.title, listing.url,
            dedup_key(listing.company, listing.title))
        record = await self.get(listing.platform, listing.external_job_id)
        assert record is not None
        return record

    async def get_application(self, application_id):
        if _uuid(application_id) is None:
            return None
        row = await self.connection.fetchrow(
            f"SELECT {self.COLUMNS} FROM public.applications WHERE id=$1::uuid", application_id)
        return _record(row) if row else None

    async def transition(self, record, target, reason, *, receipt=None, payload=None,
                         count_attempt=False, retry_after=None):
        check_transition(record.state, target)
        async with self.connection.transaction():
            row = await self.connection.fetchrow(
                f"""UPDATE public.applications
                    SET state=$1, reason=$2, receipt=COALESCE($3::jsonb, receipt),
                        attempts=attempts + $4, version=version + 1, updated_at=now(),
                        applied_at=CASE WHEN $1='APPLIED' THEN now() ELSE applied_at END,
                        retry_after=COALESCE($7::timestamptz, retry_after)
                    WHERE id=$5::uuid AND version=$6
                    RETURNING {self.COLUMNS}""",
                ApplicationState(target).value, reason,
                json.dumps(receipt, default=str) if receipt is not None else None,
                int(count_attempt), record.id, record.version, retry_after)
            if row is None:
                raise InvalidTransition("stale_version")
            await self.connection.execute(
                """INSERT INTO public.application_state_events
                       (application_id, from_state, to_state, event_type, payload)
                   VALUES ($1::uuid, $2, $3, $4, $5::jsonb)""",
                record.id, record.state.value, ApplicationState(target).value, reason[:80],
                json.dumps((payload or {}) | {"reason": reason}, default=str))
        return _record(row)

    async def find_duplicates(self, key, *, platform, external_job_id):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE dedup_key=$1 AND NOT (platform=$2 AND external_job_id=$3)
                ORDER BY updated_at DESC LIMIT 20""", key, platform, external_job_id)
        return [_record(r) for r in rows]

    async def list_by_state(self, platform, states, limit=50):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE platform=$1 AND state = ANY($2::text[])
                  AND (retry_after IS NULL OR retry_after <= now())
                ORDER BY updated_at LIMIT $3""",
            platform, [ApplicationState(s).value for s in states], limit)
        return [_record(r) for r in rows]

    async def count_state(self, state, platform=None):
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.applications WHERE state=$1 AND ($2::text IS NULL OR platform=$2)",
            ApplicationState(state).value, platform)

    async def applied_since(self, platform: str, since: datetime) -> int:
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.applications WHERE platform=$1 AND applied_at >= $2",
            platform, since)

    async def list_applications(self, query):
        where = """($1::text IS NULL OR platform=$1) AND ($2::text IS NULL OR state=$2)
                   AND ($3::timestamptz IS NULL OR updated_at >= $3)
                   AND ($4::timestamptz IS NULL OR updated_at < $4)"""
        params = (query.platform, query.state, query.since, query.until)
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications WHERE {where}
                ORDER BY updated_at DESC, id LIMIT $5 OFFSET $6""",
            *params, query.limit, query.offset)
        total = await self.connection.fetchval(
            f"SELECT count(*) FROM public.applications WHERE {where}", *params)
        return [_record(r) for r in rows], total

    async def application_events(self, application_id):
        exists = await self.connection.fetchval(
            "SELECT 1 FROM public.applications WHERE id=$1::uuid", application_id)
        if not exists:
            return None
        rows = await self.connection.fetch(
            """SELECT from_state, to_state, event_type, payload::text AS payload, created_at
               FROM public.application_state_events WHERE application_id=$1::uuid
               ORDER BY created_at, id""", application_id)
        return [dict(r) | {"payload": _json(r["payload"])} for r in rows]

    # --- auth, limits, HITL -----------------------------------------------------------
    async def record_auth(self, platform: str, status: str) -> None:
        await self.connection.execute(
            "UPDATE public.portal_rules SET auth_status=$2, auth_checked_at=now() WHERE platform=$1",
            platform, status)

    async def record_portal_limit(self, platform: str) -> None:
        await self.connection.execute(
            "UPDATE public.portal_rules SET portal_limit_hit_at=now() WHERE platform=$1", platform)

    async def create_hitl(self, record, platform, kind, prompt, context):
        return str(await self.connection.fetchval(
            """INSERT INTO public.hitl_requests (application_id, platform, kind, prompt_text, context)
               VALUES ($1::uuid, $2, $3, $4, $5::jsonb) RETURNING id""",
            record.id if record else None, platform, kind, prompt, json.dumps(context, default=str)))

    async def open_hitl_exists(self, platform, kind):
        return bool(await self.connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.hitl_requests WHERE platform=$1 AND kind=$2 AND status='OPEN')",
            platform, kind))

    async def cancel_open_hitl(self, platform, kind):
        result = await self.connection.execute(
            """UPDATE public.hitl_requests SET status='CANCELLED', resolved_at=now()
               WHERE platform=$1 AND kind=$2 AND status='OPEN'""", platform, kind)
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    HITL_SELECT = ("SELECT h.id, h.application_id, h.platform, h.kind, h.prompt_text, h.context::text AS context, "
                   "h.telegram_msg_id, h.status, h.answer_text, h.created_at, h.resolved_at, h.resolved_via, "
                   "h.consumed_at, a.company_name, a.role_title, a.job_url, a.state AS application_state "
                   "FROM public.hitl_requests h LEFT JOIN public.applications a ON a.id = h.application_id")

    async def get_hitl(self, hitl_id):
        if _uuid(hitl_id) is None:
            return None
        row = await self.connection.fetchrow(f"{self.HITL_SELECT} WHERE h.id=$1::uuid", hitl_id)
        return _hitl(row) if row else None

    async def find_open_hitl_by_ref(self, ref):
        ref = (ref or "").lower().replace("-", "")
        if not REF_PATTERN.match(ref):
            return []
        rows = await self.connection.fetch(
            f"""{self.HITL_SELECT} WHERE h.status='OPEN' AND replace(h.id::text, '-', '') LIKE $1 || '%'
                ORDER BY h.created_at LIMIT 5""", ref)
        return [_hitl(r) for r in rows]

    async def find_hitl_by_message(self, message_id):
        row = await self.connection.fetchrow(
            f"{self.HITL_SELECT} WHERE h.telegram_msg_id=$1 ORDER BY h.created_at DESC LIMIT 1", message_id)
        return _hitl(row) if row else None

    async def list_hitl(self, status="OPEN", platform=None, limit=50, offset=0):
        where = "($1::text IS NULL OR h.status=$1) AND ($2::text IS NULL OR h.platform=$2)"
        rows = await self.connection.fetch(
            f"{self.HITL_SELECT} WHERE {where} ORDER BY h.created_at, h.id LIMIT $3 OFFSET $4",
            status, platform, limit, offset)
        total = await self.connection.fetchval(
            f"SELECT count(*) FROM public.hitl_requests h WHERE {where}", status, platform)
        return [_hitl(r) for r in rows], total

    async def undelivered_hitl(self, limit=10):
        rows = await self.connection.fetch(
            f"""{self.HITL_SELECT} WHERE h.status='OPEN' AND h.telegram_msg_id IS NULL
                ORDER BY h.created_at, h.id LIMIT $1""", limit)
        return [_hitl(r) for r in rows]

    async def mark_hitl_delivered(self, hitl_id, message_id):
        await self.connection.execute(
            """UPDATE public.hitl_requests SET telegram_msg_id=$2
               WHERE id=$1::uuid AND telegram_msg_id IS NULL""", hitl_id, message_id)

    async def close_hitl(self, hitl_id, status, answer_text, via):
        if status not in HITL_STATUSES or via not in HITL_CHANNELS:
            raise ValueError("invalid hitl status or channel")
        if _uuid(hitl_id) is None:
            return None
        # Conditional on OPEN: a double-clicked button or a dashboard/Telegram race resolves once.
        closed = await self.connection.fetchval(
            """UPDATE public.hitl_requests SET status=$2, answer_text=$3, resolved_at=now(), resolved_via=$4
               WHERE id=$1::uuid AND status='OPEN' RETURNING id""", hitl_id, status, answer_text, via)
        return await self.get_hitl(str(closed)) if closed else None

    async def expire_stale_hitl(self, kind, older_than):
        """OPEN requests of `kind` created before `older_than` -> EXPIRED (conditional on OPEN)."""
        ids = await self.connection.fetch(
            """UPDATE public.hitl_requests SET status='EXPIRED', resolved_at=now(), resolved_via='worker'
               WHERE status='OPEN' AND kind=$1 AND created_at < $2 RETURNING id""", kind, older_than)
        rows = [await self.get_hitl(str(r["id"])) for r in ids]
        return [r for r in rows if r is not None]

    async def claim_digest_day(self, day):
        """Atomic once-per-local-day claim (survives restarts and two concurrent senders)."""
        await self.get_telegram_state()
        claimed = await self.connection.fetchval(
            """UPDATE public.telegram_v2_state SET last_digest_on=$1, updated_at=now()
               WHERE singleton_key='primary' AND last_digest_on IS DISTINCT FROM $1 RETURNING 1""", day)
        return bool(claimed)

    async def release_digest_day(self, day, previous):
        await self.connection.execute(
            """UPDATE public.telegram_v2_state SET last_digest_on=$2, updated_at=now()
               WHERE singleton_key='primary' AND last_digest_on=$1""", day, previous)

    async def count_open_hitl(self, platform=None):
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.hitl_requests WHERE status='OPEN' AND ($1::text IS NULL OR platform=$1)",
            platform)

    async def requeued_applications(self, platform, limit=20):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications a
                WHERE a.platform=$1 AND a.state='SCORED' AND (a.retry_after IS NULL OR a.retry_after <= now())
                  AND EXISTS (SELECT 1 FROM public.hitl_requests h WHERE h.application_id=a.id
                              AND h.status='ANSWERED' AND h.consumed_at IS NULL)
                ORDER BY a.retry_after NULLS LAST, a.updated_at LIMIT $2""", platform, limit)
        return [_record(r) for r in rows]

    async def hitl_answers(self, application_id):
        if _uuid(application_id) is None:
            return {}
        rows = await self.connection.fetch(
            """SELECT prompt_text, answer_text FROM public.hitl_requests
               WHERE application_id=$1::uuid AND status='ANSWERED' AND kind = ANY($2::text[])
                 AND answer_text IS NOT NULL ORDER BY resolved_at NULLS FIRST, created_at""",
            application_id, list(ANSWER_KINDS))
        return {r["prompt_text"]: r["answer_text"] for r in rows}

    async def mark_hitl_consumed(self, application_id):
        if _uuid(application_id) is None:
            return 0
        result = await self.connection.execute(
            """UPDATE public.hitl_requests SET consumed_at=now()
               WHERE application_id=$1::uuid AND status='ANSWERED' AND consumed_at IS NULL""",
            application_id)
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    async def get_telegram_state(self):
        row = await self.connection.fetchrow(
            """INSERT INTO public.telegram_v2_state (singleton_key) VALUES ('primary')
               ON CONFLICT (singleton_key) DO UPDATE SET singleton_key=EXCLUDED.singleton_key
               RETURNING *""")
        return TelegramState.from_row(dict(row))

    async def update_telegram_state(self, **changes):
        changes = _telegram_changes(changes)
        await self.get_telegram_state()
        columns = list(changes)
        assignments = "".join(f"{column}=${index + 1}, " for index, column in enumerate(columns))
        row = await self.connection.fetchrow(
            f"""UPDATE public.telegram_v2_state SET {assignments}updated_at=now()
                WHERE singleton_key='primary' RETURNING *""", *[changes[c] for c in columns])
        return TelegramState.from_row(dict(row))

    # --- Phase 5: quota-hit drafts + next-day retry --------------------------------------
    async def due_retries(self, platform, now, limit=20):
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications
                WHERE platform=$1 AND state='DRAFTED_AND_QUEUED' AND retry_after IS NOT NULL
                  AND retry_after <= $2
                ORDER BY retry_after, updated_at LIMIT $3""", platform, now, limit)
        return [_record(r) for r in rows]

    async def parked_since(self, platform, since):
        return await self.connection.fetchval(
            """SELECT count(*) FROM public.application_state_events e
               JOIN public.applications a ON a.id = e.application_id
               WHERE a.platform=$1 AND e.to_state='QUOTA_HIT_PENDING'
                 AND e.from_state IS DISTINCT FROM 'QUOTA_HIT_PENDING' AND e.created_at >= $2""",
            platform, since)

    DRAFT_SELECT = ("SELECT d.id, d.application_id, d.platform, d.recipient_email, d.subject, d.body_preview, "
                    "d.channel, d.status, d.composer, d.enrichment_source, d.external_draft_id, d.last_error, "
                    "d.created_at, d.updated_at, a.company_name, a.role_title, a.state AS application_state, "
                    "a.retry_after FROM public.email_drafts d "
                    "LEFT JOIN public.applications a ON a.id = d.application_id")

    async def reserve_email_draft(self, application_id, platform, recipient_email):
        if _uuid(application_id) is None:
            raise ValueError("invalid application id")
        # Atomic claim: UNIQUE(application_id) means only one caller ever owns the row.
        # A definite FAILED attempt may be re-claimed; PENDING/CREATED never are.
        claimed = await self.connection.fetchval(
            """INSERT INTO public.email_drafts (application_id, platform, recipient_email, status)
               VALUES ($1::uuid, $2, $3, 'PENDING')
               ON CONFLICT (application_id) DO UPDATE
                   SET status='PENDING', recipient_email=EXCLUDED.recipient_email, last_error=NULL,
                       updated_at=now()
                   WHERE public.email_drafts.status='FAILED'
               RETURNING id""", application_id, platform, recipient_email)
        row = await self.connection.fetchrow(
            f"{self.DRAFT_SELECT} WHERE d.application_id=$1::uuid", application_id)
        return DraftReservation(claimed is not None, _draft(row) if row else None)

    async def complete_email_draft(self, draft_id, *, channel, subject, body_preview, composer,
                                   enrichment_source, external_draft_id):
        if channel not in DRAFT_CHANNELS:
            raise ValueError("invalid draft channel")
        async with self.connection.transaction():
            application_id = await self.connection.fetchval(
                """UPDATE public.email_drafts SET status='CREATED', channel=$2, subject=$3, body_preview=$4,
                       composer=$5, enrichment_source=$6, external_draft_id=$7, last_error=NULL,
                       created_at=now(), updated_at=now()
                   WHERE id=$1::uuid AND status='PENDING' RETURNING application_id""",
                draft_id, channel, subject, _clip(body_preview, BODY_PREVIEW_CHARS), composer,
                enrichment_source, external_draft_id)
            if application_id is not None:
                await self.connection.execute(
                    """UPDATE public.applications SET draft_created_at=COALESCE(draft_created_at, now()),
                           updated_at=now() WHERE id=$1""", application_id)
        row = await self.connection.fetchrow(f"{self.DRAFT_SELECT} WHERE d.id=$1::uuid", draft_id)
        return _draft(row)

    async def fail_email_draft(self, draft_id, error, *, ambiguous=False):
        await self.connection.execute(
            """UPDATE public.email_drafts SET status=$3, last_error=$2, updated_at=now()
               WHERE id=$1::uuid AND status='PENDING'""",
            draft_id, _clip(error, 200), "PENDING" if ambiguous else "FAILED")

    async def get_email_draft(self, application_id):
        if _uuid(application_id) is None:
            return None
        row = await self.connection.fetchrow(
            f"{self.DRAFT_SELECT} WHERE d.application_id=$1::uuid", application_id)
        return _draft(row) if row else None

    async def list_email_drafts(self, platform=None, limit=50, offset=0):
        rows = await self.connection.fetch(
            f"""{self.DRAFT_SELECT} WHERE ($1::text IS NULL OR d.platform=$1)
                ORDER BY d.created_at DESC, d.id LIMIT $2 OFFSET $3""", platform, limit, offset)
        total = await self.connection.fetchval(
            "SELECT count(*) FROM public.email_drafts d WHERE ($1::text IS NULL OR d.platform=$1)", platform)
        return [_draft(r) for r in rows], total

    async def count_email_drafts(self, status="CREATED", platform=None, since=None):
        return await self.connection.fetchval(
            """SELECT count(*) FROM public.email_drafts WHERE status=$1
                   AND ($2::text IS NULL OR platform=$2) AND ($3::timestamptz IS NULL OR created_at >= $3)""",
            status, platform, since)

    # --- profile ----------------------------------------------------------------------
    async def load_profile(self):
        # to_jsonb(p) tolerates schema drift; identity fields are only used to scrub LLM prompts.
        row = await self.connection.fetchrow(
            "SELECT id, to_jsonb(p)::text AS profile FROM public.candidate_profiles p "
            "WHERE singleton_key='primary'")
        if row is None:
            return {}, []
        data = json.loads(row["profile"])
        profile = {key: data[key] for key in PROFILE_KEYS if key in data}
        profile.setdefault("verified_skills", [])
        profile.setdefault("preferences", {})
        answers = await self.connection.fetch(
            "SELECT question, answer FROM public.application_answer_drafts "
            "WHERE candidate_profile_id=$1 AND review_status='reviewed'", row["id"])
        return profile, [(a["question"], a["answer"]) for a in answers if normalize(a["question"])]

    async def update_preferences(self, changes):
        """Merge validated keys into candidate_profiles.preferences (version-checked, one statement)."""
        for _ in range(3):
            row = await self.connection.fetchrow(
                "SELECT version, preferences::text AS prefs FROM public.candidate_profiles WHERE singleton_key='primary'")
            if row is None:
                raise ProfileMissing("no_candidate_profile")
            merged = validate_preferences(json.loads(row["prefs"] or "{}") | dict(changes))
            updated = await self.connection.fetchrow(
                """UPDATE public.candidate_profiles SET preferences=$1::jsonb, version=version + 1, updated_at=now()
                   WHERE singleton_key='primary' AND version=$2 RETURNING preferences::text AS prefs""",
                json.dumps(merged), row["version"])
            if updated is not None:
                return json.loads(updated["prefs"])
        raise RevisionConflict(-1)

    # --- worker control ---------------------------------------------------------------
    async def get_worker_control(self) -> WorkerControl:
        row = await self.connection.fetchrow(
            "SELECT * FROM public.worker_control WHERE singleton_key='primary'")
        if row is None:
            row = await self.connection.fetchrow(
                """INSERT INTO public.worker_control (singleton_key) VALUES ('primary')
                   ON CONFLICT (singleton_key) DO UPDATE SET singleton_key=EXCLUDED.singleton_key
                   RETURNING *""")
        return WorkerControl.from_row(dict(row))

    async def set_worker_control(self, desired_state=None, *, dry_run=None, run_once=False):
        await self.get_worker_control()
        row = await self.connection.fetchrow(
            """UPDATE public.worker_control SET
                   desired_state=COALESCE($1, desired_state),
                   dry_run=COALESCE($2, dry_run),
                   run_once_requested_at=CASE WHEN $3 THEN now() ELSE run_once_requested_at END,
                   revision=revision + 1, updated_at=now()
               WHERE singleton_key='primary' RETURNING *""",
            WorkerState(desired_state).value if desired_state is not None else None, dry_run, run_once)
        return WorkerControl.from_row(dict(row))

    async def worker_heartbeat(self, observed_state, *, current_platform=None, last_error=None,
                               cycle_completed=False, clear_run_once=False):
        await self.connection.execute(
            """UPDATE public.worker_control SET observed_state=$1, heartbeat_at=now(),
                   current_platform=$2, last_error=$3,
                   last_cycle_at=CASE WHEN $4 THEN now() ELSE last_cycle_at END,
                   run_once_requested_at=CASE WHEN $5 THEN NULL ELSE run_once_requested_at END
               WHERE singleton_key='primary'""",
            observed_state, current_platform, (last_error or None) and last_error[:500],
            cycle_completed, clear_run_once)

    async def close(self) -> None:
        if self.owns_connection:
            await self.connection.close()

