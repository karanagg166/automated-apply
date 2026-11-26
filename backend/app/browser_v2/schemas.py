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
AdapterStatusName = Literal["ready", "pending_phase6"]


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
    label: str = Field(default="", description="Display name for the portal")
    adapter_status: AdapterStatusName = Field(
        default="pending_phase6", description="ready = a live adapter exists; pending_phase6 = rules only")
    requires_login: bool = Field(default=True, description="False for public ATS boards (Greenhouse, Lever)")
    quota_fallback_daily_cap: int = Field(default=10, description="Max new jobs drafted+queued per day once the "
                                                                    "daily quota is hit")
    quota_drafts_per_cycle: int = Field(default=5, description="Max Gmail drafts created per worker cycle")
    paused_until: datetime | None = Field(default=None, description="Portal skipped until this time (temporary pause)")
    allow_unknown_posting_age: bool = Field(
        default=False, description="Jobs whose posting date is unknown (card AND job page) pass the age filter "
                                   "instead of waiting in needs_review")
    allow_unknown_posting_age_default: bool = Field(default=False, description="Portal default for the rule above")

    @classmethod
    def from_rules(cls, rules: Any) -> PortalRulesRead:
        from backend.app.browser_v2.portals import (
            PORTALS,
            adapter_status,
            portal_label,
            unknown_age_default,
        )

        info = PORTALS.get(rules.platform)
        return cls(
            label=portal_label(rules.platform), adapter_status=adapter_status(rules.platform),
            requires_login=info.requires_login if info is not None else True,
            platform=rules.platform, enabled=rules.enabled, auto_apply_enabled=rules.auto_apply_enabled,
            max_applies_per_day=rules.max_applies_per_day, max_applies_per_hour=rules.max_applies_per_hour,
            max_job_age_days=rules.max_job_age_days, max_applicants=rules.max_applicants,
            unknown_applicants_policy=str(rules.unknown_applicants_policy),  # type: ignore[arg-type]
            min_delay_sec=rules.min_delay_sec, max_delay_sec=rules.max_delay_sec,
            active_hours_start=hhmm(rules.active_hours_start), active_hours_end=hhmm(rules.active_hours_end),
            timezone=rules.timezone, auth_status=rules.auth_status,
            auth_checked_at=rules.auth_checked_at, portal_limit_hit_at=rules.portal_limit_hit_at,
            revision=rules.revision, updated_at=rules.updated_at,
            quota_fallback_daily_cap=_effective_cap(rules), quota_drafts_per_cycle=_effective_drafts(rules),
            paused_until=getattr(rules, "paused_until", None),
            allow_unknown_posting_age=bool(getattr(rules, "unknown_age_allowed", False)),
            allow_unknown_posting_age_default=unknown_age_default(rules.platform))


def _effective_cap(rules: Any) -> int:
    from backend.app.browser_v2.quota import fallback_daily_cap

    return fallback_daily_cap(rules)


def _effective_drafts(rules: Any) -> int:
    from backend.app.browser_v2.rules import DEFAULT_QUOTA_DRAFTS_PER_CYCLE

    value = getattr(rules, "quota_drafts_per_cycle", None)
    return DEFAULT_QUOTA_DRAFTS_PER_CYCLE if value is None else int(value)


NULLABLE_RULE_FIELDS = frozenset({"active_hours_start", "active_hours_end", "paused_until"})


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
    quota_fallback_daily_cap: int | None = Field(default=None, ge=0, le=100)
    quota_drafts_per_cycle: int | None = Field(default=None, ge=0, le=50)
    paused_until: datetime | None = Field(default=None, description="null = resume now")
    allow_unknown_posting_age: StrictBool | None = None

    @field_validator("paused_until")
    @classmethod
    def aware_pause(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("paused_until must include a timezone offset")
        return value

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
    "skill_years", "country", "current_company", "english_proficiency",
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


# --- Phase 5: quota-hit Gmail drafts, enrichment and the mail bridge ----------------------
DraftChannelName = Literal["imap", "mail_app"]
DraftStatusName = Literal["PENDING", "CREATED", "FAILED"]
GMAIL_PERMISSION_LABEL = "Gmail Permission: Read + Draft Only (Sending Disabled)"


class EmailDraftRead(BaseModel):
    id: str
    application_id: str | None
    platform: str | None
    company_name: str | None
    role_title: str | None
    recipient_email: str | None
    subject: str | None
    body_preview: str | None
    channel: DraftChannelName | None
    status: DraftStatusName
    composer: Literal["llm", "template"] | None
    enrichment_source: str | None
    last_error: str | None
    created_at: datetime | None
    application_state: str | None = Field(description="Current application state (retry status)")
    retry_after: datetime | None = Field(description="Next portal retry (DRAFTED_AND_QUEUED)")


class EmailDraftPage(BaseModel):
    items: list[EmailDraftRead]
    total: int
    limit: int
    offset: int


class EnrichmentProviderRead(BaseModel):
    provider: Literal["apollo", "apify", "signalhire"]
    configured: bool
    state: Literal["unconfigured", "available", "cooldown", "cap_reached"]
    daily_cap: int
    used_today: int
    period_key: str = Field(description="YYYY-MM-DD in Asia/Kolkata")
    cooldown_until: datetime | None
    last_error: str | None
    key_env: str = Field(description="Env var that configures the provider (value never returned)")


class EnrichmentStatusRead(BaseModel):
    backend: Literal["postgres", "memory"]
    disabled: bool
    fetch_pages: bool
    providers: list[EnrichmentProviderRead]
    cached_domains: int


class MailStatusRead(BaseModel):
    permission: Literal["READ_AND_DRAFT_ONLY"] = "READ_AND_DRAFT_ONLY"
    permission_label: str = GMAIL_PERMISSION_LABEL
    disabled: bool
    channel_mode: Literal["auto", "imap", "mail_app"]
    active_channel: Literal["imap", "mail_app", "unconfigured"]
    imap_configured: bool
    imap_email: str | None = Field(description="Masked address, e.g. ka•••@gmail.com")
    imap_host: str
    mail_app_available: bool
    mail_app_disabled: bool
    resume_attachment_configured: bool


class DraftNowRead(BaseModel):
    ok: bool
    code: Literal["drafted", "already_drafted", "no_email_found", "draft_failed", "mail_unconfigured"]
    message: str
    channel: DraftChannelName | None = None
    enrichment_status: str | None = None
    enrichment_source: str | None = None
    draft: EmailDraftRead | None = None


# --- Phase 6A: control agent, event bus, read-only recruiter replies ----------------------
class AgentChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000, description="Owner message, e.g. 'pause Internshala for 3 hours'")


class AgentChatRead(BaseModel):
    reply: str
    tool: str | None = None
    source: str | None = Field(default=None, description="deterministic | llm")
    verdict: str | None = Field(default=None, description="ok | rejected | confirm | help")
    ok: bool


class EventBusStatusRead(BaseModel):
    backend: Literal["postgres", "cloudamqp", "upstash_redis", "in_process"]
    requested_backend: str
    fell_back: bool
    healthy: bool
    published: int = 0
    handler_errors: int = 0
    topics: list[str]
    remote: dict[str, Any] | None = None
    process_note: str = "The worker process owns the live bus; this shows the configured backend."


class MailEventRead(BaseModel):
    id: str | None = None
    kind: Literal["RECRUITER_REPLY", "INTERVIEW", "JOB_ALERT"]
    source: str
    platform: str | None = None
    company_name: str | None = None
    sender: str | None = None
    subject: str | None = None
    snippet: str | None = None
    application_id: str | None = None
    received_at: datetime | None = None
    alerted_at: datetime | None = None
    created_at: datetime | None = None


class MailReplyPage(BaseModel):
    permission: Literal["READ_ONLY"] = "READ_ONLY"
    configured: bool
    tiers: dict[str, bool]
    items: list[MailEventRead]
