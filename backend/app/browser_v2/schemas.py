"""Pydantic contracts for the v2 dashboard API (portal rules, screening facts, worker)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    create_model,
    field_validator,
    model_validator,
)

from backend.app.schemas.candidate_profile import JobSearchPreferences

ApplicantPolicyName = Literal["allow_lower_bound", "allow", "skip", "needs_review"]
WorkerStateName = Literal["RUNNING", "PAUSED", "STOPPED"]


def hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


class PortalRulesRead(BaseModel):
    platform: str
    enabled: bool
    auto_apply_enabled: bool
    max_applies_per_day: int
    max_applies_per_hour: int
    max_job_age_days: int
    max_applicants: int
    unknown_applicants_policy: ApplicantPolicyName
    min_delay_sec: int
    max_delay_sec: int
    active_hours_start: str | None = Field(description="HH:MM in `timezone`; null = all day")
    active_hours_end: str | None
    timezone: str
    auth_status: Literal["OK", "AUTH_REQUIRED", "UNKNOWN"]
    auth_checked_at: datetime | None = None
    portal_limit_hit_at: datetime | None = None
    revision: int
    updated_at: datetime | None = None

    @classmethod
    def from_rules(cls, rules: Any) -> PortalRulesRead:
        return cls(
            platform=rules.platform, enabled=rules.enabled, auto_apply_enabled=rules.auto_apply_enabled,
            max_applies_per_day=rules.max_applies_per_day, max_applies_per_hour=rules.max_applies_per_hour,
            max_job_age_days=rules.max_job_age_days, max_applicants=rules.max_applicants,
            unknown_applicants_policy=str(rules.unknown_applicants_policy),  # type: ignore[arg-type]
            min_delay_sec=rules.min_delay_sec, max_delay_sec=rules.max_delay_sec,
            active_hours_start=hhmm(rules.active_hours_start), active_hours_end=hhmm(rules.active_hours_end),
            timezone=rules.timezone, auth_status=rules.auth_status,
            auth_checked_at=rules.auth_checked_at, portal_limit_hit_at=rules.portal_limit_hit_at,
            revision=rules.revision, updated_at=rules.updated_at)


NULLABLE_RULE_FIELDS = frozenset({"active_hours_start", "active_hours_end"})


class PortalRulesPatch(BaseModel):
    """Partial update. `revision` must equal the current row (optimistic concurrency)."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    enabled: StrictBool | None = None
    auto_apply_enabled: StrictBool | None = None
    max_applies_per_day: int | None = Field(default=None, ge=1, le=500)
    max_applies_per_hour: int | None = Field(default=None, ge=1, le=100)
    max_job_age_days: int | None = Field(default=None, ge=1, le=365)
    max_applicants: int | None = Field(default=None, ge=1, le=100_000)
    unknown_applicants_policy: ApplicantPolicyName | None = None
    min_delay_sec: int | None = Field(default=None, ge=5, le=3600)
    max_delay_sec: int | None = Field(default=None, ge=5, le=7200)
    active_hours_start: time | None = None
    active_hours_end: time | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("active_hours_start", "active_hours_end")
    @classmethod
    def minute_precision(cls, value: time | None) -> time | None:
        return value.replace(second=0, microsecond=0, tzinfo=None) if value is not None else value

    @model_validator(mode="after")
    def require_change(self) -> PortalRulesPatch:
        changed = self.model_fields_set - {"revision"}
        if not changed:
            raise ValueError("Supply at least one rule to change")
        nulls = [name for name in changed if getattr(self, name) is None and name not in NULLABLE_RULE_FIELDS]
        if nulls:
            raise ValueError(f"These rules cannot be null: {', '.join(sorted(nulls))}")
        return self

    def changes(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.model_fields_set - {"revision"}}


SCREENING_FIELDS = (
    "target_roles", "keywords_required", "keywords_excluded", "tech_stack", "company_blacklist",
    "remote_policy", "skill_match_mode", "min_match_score", "current_ctc", "expected_ctc", "min_ctc",
    "notice_period_days", "total_experience_years", "current_location", "willing_to_relocate",
    "skill_years",
)


class _ScreeningBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# Field types/constraints are copied from JobSearchPreferences so both APIs validate identically.
_fields: dict[str, Any] = {
    name: (JobSearchPreferences.model_fields[name].rebuild_annotation(),
           JobSearchPreferences.model_fields[name])
    for name in SCREENING_FIELDS
}
ScreeningFacts = create_model("ScreeningFacts", __base__=_ScreeningBase, **_fields)


class ScreeningProfileRead(ScreeningFacts):  # type: ignore[misc, valid-type]
    version: int = Field(description="candidate_profiles.version; send back on PATCH")
    has_profile: bool = True


_patch_fields: dict[str, Any] = {
    name: (JobSearchPreferences.model_fields[name].rebuild_annotation(), None) for name in SCREENING_FIELDS
}
_ScreeningPatchBase = create_model(
    "_ScreeningPatchBase", __base__=_ScreeningBase, **_patch_fields)


class ScreeningProfilePatch(_ScreeningPatchBase):  # type: ignore[misc, valid-type]
    version: int = Field(ge=1, description="Current candidate_profiles.version")

    @model_validator(mode="after")
    def require_change(self) -> ScreeningProfilePatch:
        if not (self.model_fields_set - {"version"}):
            raise ValueError("Supply at least one screening fact to change")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(mode="json", include=self.model_fields_set - {"version"})


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


# --- Phase 4: Telegram HITL + dashboard inbox -------------------------------------------
HitlKindName = Literal["CAPTCHA", "OTP", "AUTH", "QUESTION", "ERROR"]
HitlStatusName = Literal["OPEN", "ANSWERED", "EXPIRED", "CANCELLED"]
PollingStateName = Literal["unconfigured", "starting", "polling", "conflict", "error", "stopped"]


class HitlRead(BaseModel):
    id: str
    ref: str
    application_id: str | None
    platform: str
    kind: HitlKindName
    status: HitlStatusName
    question: str
    options: list[str]
    resolver_reason: str | None
    company: str | None
    title: str | None
    job_url: str | None
    application_state: str | None
    telegram_msg_id: int | None
    answer_text: str | None
    resolved_via: str | None
    created_at: datetime | None
    resolved_at: datetime | None
    consumed_at: datetime | None


class HitlPage(BaseModel):
    items: list[HitlRead]
    total: int
    limit: int
    offset: int


class HitlResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=1000)
    cache_answer: StrictBool = True


class HitlResolutionRead(BaseModel):
    ok: bool
    code: str
    message: str
    answer: str | None
    cached: bool
    requeued: bool
    application_state: str | None
    options: list[str]
    hitl: HitlRead | None


class TelegramStatusRead(BaseModel):
    configured: bool
    polling_state: PollingStateName
    stale: bool
    conflict_detected: bool
    conflict_detected_at: datetime | None
    last_poll_at: datetime | None
    last_update_id: int | None
    last_error: str | None
    owner_chat_id: str | None
    open_hitl_count: int


class ResumeAuthRead(BaseModel):
    ok: bool
    platform: str
    message: str
    auth_status: str | None
    resolved_auth_requests: int
