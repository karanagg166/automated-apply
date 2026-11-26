"""Agent guardrails: forbidden capabilities, the never-replay fence, risky-change rules and
sanitized audit summaries (no secrets, OTPs or raw PII ever reach agent_audit_log)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

from backend.app.agent_v2.tools.base import CONFIRM_DAILY_ABOVE, GuardrailViolation
from backend.app.ai_v2.pii import scrub_pii
from backend.app.browser_v2.store import FENCED_STATES

# No tool may ever be able to send, mail, deliver, delete or replay anything.
FORBIDDEN_TOOL_WORDS = ("send", "mail", "deliver", "delete", "replay")
# Rule-patch keys the agent may never touch (system-managed or never-replay related).
FORBIDDEN_PATCH_KEYS = frozenset({"send", "send_email", "delete", "drop", "replay", "state", "applied_at",
                                  "receipt", "auth_status", "revision", "portal_limit_hit_at", "circuit_failures",
                                  "circuit_level", "circuit_open_until", "circuit_reason", "last_fresh_sweep_at",
                                  "auth_checked_at", "updated_at"})
MAX_PORTALS_WITHOUT_CONFIRM = 3
# Argument values never written to the audit log in clear (HITL answers can be OTPs).
REDACTED_ARGS = {"resolve_hitl_via_agent": ("answer",), "upsert_qa_fact": ()}
FENCE_MESSAGE = ("Never-replay fence: {state} applications may already have reached the employer, so they are "
                 "never modified, re-queued or re-prioritised.")


def check_tool_name(name: str) -> None:
    if any(word in name for word in FORBIDDEN_TOOL_WORDS):
        raise GuardrailViolation(f"forbidden tool name: {name}")


def fence_reason(state: Any) -> str | None:
    value = getattr(state, "value", state)
    return FENCE_MESSAGE.format(state=value) if value in FENCED_STATES else None


def check_fence(record: Any) -> None:
    """Agent-side fence (the store enforces the same rule in its write methods)."""
    reason = fence_reason(getattr(record, "state", None)) if record is not None else None
    if reason:
        raise GuardrailViolation(reason)


def forbidden_patch_keys(patch: dict[str, Any]) -> list[str]:
    return sorted(set(patch) & FORBIDDEN_PATCH_KEYS)


def rule_patch_risk(portals: list[str], patch: dict[str, Any]) -> str | None:
    """>3 portals, enabling auto-apply or a daily cap above 100 needs an explicit confirmation."""
    if patch.get("auto_apply_enabled") is True:
        return "enables auto-apply (live submissions)"
    try:
        daily = int(patch.get("max_applies_per_day") or 0)
    except (TypeError, ValueError):
        daily = 0
    if daily > CONFIRM_DAILY_ABOVE:
        return f"daily cap above {CONFIRM_DAILY_ABOVE}"
    if len(portals) > MAX_PORTALS_WITHOUT_CONFIRM and "paused_until" not in patch:
        return f"changes {len(portals)} portals at once"
    return None


def sanitize(value: Any, secrets: Iterable[str] = (), *, depth: int = 0) -> Any:
    """JSON-safe, size-bounded copy with every string PII-scrubbed (for audit summaries)."""
    if depth > 4:
        return "[…]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, dict):
        return {str(k)[:60]: sanitize(v, secrets, depth=depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize(v, secrets, depth=depth + 1) for v in list(value)[:30]]
    text = scrub_pii(str(value), secrets)
    return text if len(text) <= 300 else text[:299] + "…"


def audit_args(tool_name: str, args: dict[str, Any], secrets: Iterable[str] = ()) -> dict[str, Any]:
    redacted = REDACTED_ARGS.get(tool_name, ())
    shown = {k: ("[redacted]" if k in redacted and v else v) for k, v in args.items()}
    result = sanitize(shown, secrets)
    return result if isinstance(result, dict) else {}
