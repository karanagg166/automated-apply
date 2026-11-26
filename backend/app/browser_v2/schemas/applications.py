"""Application, worker-control and automation-status contracts."""

from __future__ import annotations

from datetime import datetime
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
