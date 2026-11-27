"""Application, worker-control and automation-status contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.app.browser_v2.schemas.portal_rules import WorkerStateName


class ApplicationRead(BaseModel):
    id: str
    platform: str
    external_job_id: str
    company_name: str | None = None
    role_title: str | None = None
    job_url: str | None = None
    state: str
    reason: str | None = None
    attempts: int = 0
    applied_at: datetime | None = None
    retry_after: datetime | None = None
    draft_created_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Milestone 2 mail funnel: latest stage from post-apply mail (OA_INVITE | INTERVIEW_INVITE |
    # RECRUITER_REPLY | REJECTED) and whether a confirmation email verified the submission.
    funnel_stage: str | None = None
    email_verified: bool = False


class ApplicationPage(BaseModel):
    items: list[ApplicationRead]
    total: int
    limit: int
    offset: int


class StateEventRead(BaseModel):
    from_state: str | None = None
    to_state: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class PortalSummary(BaseModel):
    platform: str = Field(description="Portal key, or 'all' for the overall totals")
    applied_total: int = 0
    applied_today: int = Field(0, description="APPLIED with applied_at on the current local day")
    applied_7d: int = Field(0, description="APPLIED with applied_at in the last 7 local days (incl. today)")
    submission_unknown: int = 0
    failed: int = 0
    waiting_for_user: int = 0
    applying: int = 0
    queued: int = Field(0, description="DISCOVERED + SCORED (not yet attempted)")
    quota_parked: int = Field(0, description="QUOTA_HIT_PENDING + DRAFTED_AND_QUEUED")
    filtered_out: int = 0
    total: int = 0
    states: dict[str, int] = Field(default_factory=dict, description="Current count per state")


class DailyApplied(BaseModel):
    date: date
    applied: int
    by_platform: dict[str, int] = Field(default_factory=dict)


class ApplicationSummary(BaseModel):
    generated_at: datetime
    timezone: str
    days: int
    totals: PortalSummary
    portals: list[PortalSummary]
    daily: list[DailyApplied] = Field(description="Oldest first, one entry per local day (zeros included)")


class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    source: str | None = None


class ReceiptSummary(BaseModel):
    """Safe projection of `applications.receipt` + the latest apply event (no paths, no raw JSON)."""
    verified: bool = False
    source: str | None = None
    ats: str | None = None
    portal_status: str | None = None
    verified_at: datetime | None = None
    confirmation_url: str | None = None
    external_url: str | None = None
    resume: str | None = None
    clicked_apply: bool | None = None
    has_screenshot: bool = False
    answers: list[ScreeningAnswer] = Field(default_factory=list)
    answers_source: Literal["receipt", "event"] | None = None


class TimelineEvent(BaseModel):
    from_state: str | None = None
    to_state: str
    event_type: str
    created_at: datetime | None = None


class ApplicationDetail(ApplicationRead):
    receipt: ReceiptSummary
    timeline: list[TimelineEvent] = Field(default_factory=list)


class WorkerControlRead(BaseModel):
    desired_state: WorkerStateName
    dry_run: bool
    run_once_requested_at: datetime | None = None
    observed_state: str
    heartbeat_at: datetime | None = None
    heartbeat_age_sec: float | None = None
    stale: bool = Field(description="No heartbeat for 5+ minutes (worker process not running)")
    current_platform: str | None = None
    last_cycle_at: datetime | None = None
    last_error: str | None = None
    revision: int


class WorkerStartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: StrictBool | None = Field(default=None, description="false = live applications")


class PortalStatus(BaseModel):
    platform: str
    enabled: bool
    auto_apply_enabled: bool
    auth_status: str
    auth_checked_at: datetime | None = None
    portal_limit_hit_at: datetime | None = None
    portal_limit_hit_today: bool
    applied_today: int
    max_applies_per_day: int
    applied_this_hour: int
    max_applies_per_hour: int
    daily_limit_hit: bool
    hourly_limit_hit: bool
    within_active_hours: bool
    waiting_for_user: int


class AutomationStatus(BaseModel):
    generated_at: datetime
    gmail_permission: Literal["read_draft_only"] = "read_draft_only"
    gmail_permission_label: str = "Gmail Permission: Read + Draft Only (Sending Disabled)"
    waiting_for_user: int
    worker: WorkerControlRead
    portals: list[PortalStatus]
