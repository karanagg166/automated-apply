"""Per-portal rules (public.portal_rules): policy, overrides, pause and active hours."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, time
from enum import StrEnum
from typing import Any

from backend.app.browser_v2.portals import PORTALS


class ApplicantPolicy(StrEnum):
    ALLOW_LOWER_BOUND = "allow_lower_bound"
    ALLOW = "allow"
    SKIP = "skip"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PortalRules:
    platform: str
    enabled: bool = False
    auto_apply_enabled: bool = False
    max_applies_per_day: int = 50
    max_applies_per_hour: int = 10
    max_job_age_days: int = 7
    max_applicants: int = 300
    unknown_applicants_policy: ApplicantPolicy = ApplicantPolicy.ALLOW_LOWER_BOUND
    min_delay_sec: int = 45
    max_delay_sec: int = 150
    active_hours_start: time | None = time(8, 0)
    active_hours_end: time | None = time(23, 30)
    timezone: str = "Asia/Kolkata"
    auth_status: str = "UNKNOWN"
    revision: int = 1
    auth_checked_at: datetime | None = None
    portal_limit_hit_at: datetime | None = None
    updated_at: datetime | None = None
    # Phase 6A (dashboard-editable). None = a pre-6A row: env/default caps apply.
    quota_fallback_daily_cap: int | None = None
    quota_drafts_per_cycle: int | None = None
    paused_until: datetime | None = None  # temporary owner pause (agent / dashboard)
    # Phase 8: None = the portal default (portals.PortalInfo.allow_unknown_age_default). Stored
    # without a migration in candidate_profiles.preferences.portal_rule_overrides (JSONB).
    allow_unknown_posting_age: bool | None = None
    # Phase 9B (followup 005, system-managed, never dashboard-editable): persisted per-portal
    # circuit breaker and the last fresh-first sweep. Older rows without the columns keep the defaults.
    circuit_failures: int = 0
    circuit_level: int = 0
    circuit_open_until: datetime | None = None
    circuit_reason: str | None = None
    last_fresh_sweep_at: datetime | None = None

    @property
    def unknown_age_allowed(self) -> bool:
        if self.allow_unknown_posting_age is not None:
            return bool(self.allow_unknown_posting_age)
        from backend.app.browser_v2.portals import unknown_age_default

        return unknown_age_default(self.platform)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalRules:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in dict(row).items() if k in known}
        if "unknown_applicants_policy" in values:
            values["unknown_applicants_policy"] = ApplicantPolicy(values["unknown_applicants_policy"])
        for counter in ("circuit_failures", "circuit_level"):
            if values.get(counter) is None:
                values.pop(counter, None)
        return cls(**values)


# Owner-editable columns (dashboard PATCH). auth_status/revision are system-managed.
EDITABLE_RULE_FIELDS = (
    "enabled", "auto_apply_enabled", "max_applies_per_day", "max_applies_per_hour",
    "max_job_age_days", "max_applicants", "unknown_applicants_policy", "min_delay_sec",
    "max_delay_sec", "active_hours_start", "active_hours_end", "timezone",
    "quota_fallback_daily_cap", "quota_drafts_per_cycle", "paused_until",
)
# Owner-editable rules persisted in candidate_profiles.preferences.portal_rule_overrides
# (JSONB) instead of a portal_rules column, so no admin SQL migration is needed.
OVERRIDE_RULE_FIELDS = ("allow_unknown_posting_age",)
ALL_EDITABLE_RULE_FIELDS = EDITABLE_RULE_FIELDS + OVERRIDE_RULE_FIELDS


def apply_overrides(rules: PortalRules, overrides: dict[str, Any] | None) -> PortalRules:
    """Overlay preferences.portal_rule_overrides[platform] onto a portal_rules row."""
    from dataclasses import replace as _replace

    entry = (overrides or {}).get(rules.platform)
    if not isinstance(entry, dict):
        return rules
    value = entry.get("allow_unknown_posting_age")
    return _replace(rules, allow_unknown_posting_age=value) if isinstance(value, bool) else rules
DEFAULT_QUOTA_FALLBACK_DAILY_CAP = 10
DEFAULT_QUOTA_DRAFTS_PER_CYCLE = 5


def paused(rules: PortalRules, now: datetime) -> bool:
    return rules.paused_until is not None and rules.paused_until > now


def within_active_hours(rules: PortalRules, now: datetime) -> bool:
    """Active window in the portal timezone; supports windows that cross midnight."""
    from zoneinfo import ZoneInfo

    if rules.active_hours_start is None or rules.active_hours_end is None:
        return True
    local = now.astimezone(ZoneInfo(rules.timezone)).time().replace(tzinfo=None)
    start, end = rules.active_hours_start, rules.active_hours_end
    if start == end:
        return True
    if start < end:
        return start <= local < end
    return local >= start or local < end


# Mirrors the migration 004 seed (+ Phase 8b self-seed): all 15 portals, only naukri enabled by default.
DEFAULT_RULES = {name: PortalRules(platform=name, enabled=info.default_enabled)
                 for name, info in PORTALS.items()}
