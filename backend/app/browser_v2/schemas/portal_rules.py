"""Portal rules read/patch contracts."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

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
    # Phase 9B read-only (system-managed; not accepted by PortalRulesPatch).
    circuit_failures: int = Field(default=0, description="Consecutive portal failures (circuit breaker)")
    circuit_level: int = Field(default=0, description="Circuit back-off level; 0 = closed")
    circuit_open_until: datetime | None = Field(default=None, description="Portal skipped until this time")
    circuit_reason: str | None = None
    last_fresh_sweep_at: datetime | None = Field(default=None, description="Last fresh-first discovery sweep")

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
            unknown_applicants_policy=str(rules.unknown_applicants_policy),  # type: ignore[arg-type, unused-ignore]
            min_delay_sec=rules.min_delay_sec, max_delay_sec=rules.max_delay_sec,
            active_hours_start=hhmm(rules.active_hours_start), active_hours_end=hhmm(rules.active_hours_end),
            timezone=rules.timezone, auth_status=rules.auth_status,
            auth_checked_at=rules.auth_checked_at, portal_limit_hit_at=rules.portal_limit_hit_at,
            revision=rules.revision, updated_at=rules.updated_at,
            quota_fallback_daily_cap=_effective_cap(rules), quota_drafts_per_cycle=_effective_drafts(rules),
            paused_until=getattr(rules, "paused_until", None),
            allow_unknown_posting_age=bool(getattr(rules, "unknown_age_allowed", False)),
            allow_unknown_posting_age_default=unknown_age_default(rules.platform),
            circuit_failures=int(getattr(rules, "circuit_failures", 0) or 0),
            circuit_level=int(getattr(rules, "circuit_level", 0) or 0),
            circuit_open_until=getattr(rules, "circuit_open_until", None),
            circuit_reason=getattr(rules, "circuit_reason", None),
            last_fresh_sweep_at=getattr(rules, "last_fresh_sweep_at", None))


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
