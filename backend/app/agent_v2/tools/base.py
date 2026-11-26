"""Shared tool result type, guardrail errors and the dashboard-equivalent rule validation.

Every write goes through the same validation as the dashboard API (PortalRulesPatch +
cross-field checks, JobSearchPreferences) and the single v2 store connection; there is no
send, delete or replay tool at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from backend.app.browser_v2.portals import PORTALS
from backend.app.browser_v2.schemas import PortalRulesPatch

PREFERENCE_LISTS = ("company_blacklist", "keywords_required", "keywords_excluded", "tech_stack", "target_roles")
PREFERENCE_SCALARS = ("expected_ctc", "current_ctc", "min_ctc", "notice_period_days", "remote_policy",
                      "total_experience_years", "current_location", "willing_to_relocate", "min_match_score",
                      "skill_match_mode")
# Changes that need an explicit "confirm" in the same message.
CONFIRM_DAILY_ABOVE = 100


class GuardrailViolation(ValueError):
    pass


class NeedsConfirmation(ValueError):
    pass


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    # Phase 9C: code-rendered HTML change block for the owner (the LLM never describes changes),
    # the compact observation handed back to the LLM, the audited outcome and a confirmation token.
    user_html: str | None = None
    llm_summary: str | None = None
    outcome: str = "ok"  # ok | refused | error | needs_confirmation | cancelled
    token: str | None = None


def resolve_platforms(platforms: list[str] | None) -> list[str]:
    names = list(dict.fromkeys(platforms or []))
    if not names:
        raise GuardrailViolation("Which portal? e.g. 'enable Instahyre' or 'set Naukri daily limit to 60'.")
    if "*" in names:
        return sorted(PORTALS)
    unknown = [n for n in names if n not in PORTALS]
    if unknown:
        raise GuardrailViolation(f"Unknown portal: {', '.join(unknown)}")
    return names


def validate_rule_changes(platforms: list[str], changes: dict[str, Any], rules_by_platform: dict[str, Any], *,
                          confirmed: bool) -> dict[str, dict[str, Any]]:
    """Same checks as PATCH /api/v1/v2/portal-rules (Pydantic ranges + cross-field rules)."""
    if not changes:
        raise GuardrailViolation("No rule change found.")
    plan: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        current = rules_by_platform.get(platform)
        if current is None:
            raise GuardrailViolation(f"Unknown portal: {platform}")
        try:
            patch = PortalRulesPatch.model_validate({"revision": current.revision, **changes})
        except ValidationError as exc:
            first = exc.errors()[0]
            raise GuardrailViolation(f"Rejected: {'.'.join(str(p) for p in first['loc'])} {first['msg']}") from None
        values = patch.changes()
        merged = {name: values.get(name, getattr(current, name)) for name in
                  ("min_delay_sec", "max_delay_sec", "max_applies_per_hour", "max_applies_per_day")}
        if merged["max_delay_sec"] < merged["min_delay_sec"]:
            raise GuardrailViolation("Rejected: max delay must be >= min delay.")
        if merged["max_applies_per_hour"] > merged["max_applies_per_day"]:
            raise GuardrailViolation("Rejected: hourly cap cannot exceed the daily cap.")
        if not confirmed and (values.get("auto_apply_enabled") is True
                              or (values.get("max_applies_per_day") or 0) > CONFIRM_DAILY_ABOVE
                              or len(platforms) > 3 and "paused_until" not in values):
            raise NeedsConfirmation("This is a high-impact change. Resend the same message with the word "
                                    "'confirm' to apply it.")
        plan[platform] = values
    return plan



def _show(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "(empty)"
    if value is None:
        return "cleared"
    if isinstance(value, timedelta):
        return str(value)
    return str(value)
