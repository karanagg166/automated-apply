"""Phase 9B: one failure/outcome taxonomy for all portals.

Adapters keep emitting their detailed ``reason`` strings (they are stored and shown to the
owner); :func:`classify` maps every (state, reason) pair onto exactly one :class:`OutcomeCode`
so the worker, circuit breaker, Telegram and analytics reason about outcomes uniformly.
Pure domain: no I/O.
"""

from __future__ import annotations

from enum import StrEnum

from backend.app.browser_v2.state import ApplicationState


class OutcomeCode(StrEnum):
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    CLOSED_JOB = "CLOSED_JOB"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA_WALL = "CAPTCHA_WALL"
    EXTERNAL_UNSUPPORTED_ATS = "EXTERNAL_UNSUPPORTED_ATS"
    EXTERNAL_ATS_HANDED_OFF = "EXTERNAL_ATS_HANDED_OFF"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    QUOTA_HIT = "QUOTA_HIT"
    DOM_CHANGED = "DOM_CHANGED"
    INFRA_ERROR = "INFRA_ERROR"
    DRY_RUN_STOPPED = "DRY_RUN_STOPPED"
    FILTERED = "FILTERED"


# Outcomes that count toward a portal's circuit breaker (infrastructure, DOM drift, walls).
BREAKER_OUTCOMES = frozenset({OutcomeCode.INFRA_ERROR, OutcomeCode.DOM_CHANGED, OutcomeCode.CAPTCHA_WALL})

# Ordered (prefix, code) rules; the first matching prefix wins. Exact reasons are prefixes too.
_RULES: tuple[tuple[str, OutcomeCode], ...] = (
    ("confirmed", OutcomeCode.APPLIED),
    ("verified_in_portal_history", OutcomeCode.APPLIED),
    ("already_applied_on_portal", OutcomeCode.ALREADY_APPLIED),
    ("job_closed", OutcomeCode.CLOSED_JOB),
    ("ats_posting_closed", OutcomeCode.CLOSED_JOB),
    ("quota_retry_expired", OutcomeCode.CLOSED_JOB),
    ("portal_login_required", OutcomeCode.AUTH_REQUIRED),
    ("auth_required", OutcomeCode.AUTH_REQUIRED),
    ("otp_unavailable", OutcomeCode.AUTH_REQUIRED),
    ("portal_daily_limit", OutcomeCode.QUOTA_HIT),
    ("portal_limit", OutcomeCode.QUOTA_HIT),
    ("dashboard_daily_limit", OutcomeCode.QUOTA_HIT),
    ("dashboard_hourly_limit", OutcomeCode.QUOTA_HIT),
    ("daily_limit_hit", OutcomeCode.QUOTA_HIT),
    ("hourly_limit_hit", OutcomeCode.QUOTA_HIT),
    ("quota_", OutcomeCode.QUOTA_HIT),
    ("portal_wall", OutcomeCode.CAPTCHA_WALL),
    ("challenge_after_apply_click", OutcomeCode.CAPTCHA_WALL),
    ("ats_captcha_before_submit", OutcomeCode.CAPTCHA_WALL),
    ("portal_", OutcomeCode.CAPTCHA_WALL),  # portal_<challenge>: captcha / cloudflare / blocked
    ("ats_handoff:", OutcomeCode.EXTERNAL_ATS_HANDED_OFF),
    ("external_unsupported_ats", OutcomeCode.EXTERNAL_UNSUPPORTED_ATS),
    ("external_company_site", OutcomeCode.EXTERNAL_UNSUPPORTED_ATS),
    ("dry_run_stopped", OutcomeCode.DRY_RUN_STOPPED),
    ("question_requires_owner", OutcomeCode.NEEDS_REVIEW),
    ("questionnaire_unsupported_control", OutcomeCode.NEEDS_REVIEW),
    ("ats_validation_errors", OutcomeCode.NEEDS_REVIEW),
    ("apply_control_unsupported_ui", OutcomeCode.NEEDS_REVIEW),
    ("apply_control_ambiguous", OutcomeCode.NEEDS_REVIEW),
    ("needs_review", OutcomeCode.NEEDS_REVIEW),
    ("confirmation_ambiguous", OutcomeCode.SUBMISSION_UNKNOWN),
    ("questionnaire_stalled", OutcomeCode.SUBMISSION_UNKNOWN),
    ("questionnaire_step_limit", OutcomeCode.SUBMISSION_UNKNOWN),
    ("form_step_limit", OutcomeCode.SUBMISSION_UNKNOWN),
    ("apply_control_none", OutcomeCode.CLOSED_JOB),
    ("apply_control_", OutcomeCode.DOM_CHANGED),
    ("ats_submit_control_", OutcomeCode.DOM_CHANGED),
    ("dry_run_form_not_found", OutcomeCode.DOM_CHANGED),
    ("consecutive_errors", OutcomeCode.INFRA_ERROR),
    ("infra_error", OutcomeCode.INFRA_ERROR),
    ("duplicate_of", OutcomeCode.FILTERED),
)

_STATE_DEFAULT: dict[ApplicationState, OutcomeCode] = {
    ApplicationState.APPLIED: OutcomeCode.APPLIED,
    ApplicationState.SUBMISSION_UNKNOWN: OutcomeCode.SUBMISSION_UNKNOWN,
    ApplicationState.FILTERED_OUT: OutcomeCode.FILTERED,
    ApplicationState.WAITING_FOR_USER: OutcomeCode.NEEDS_REVIEW,
    ApplicationState.QUOTA_HIT_PENDING: OutcomeCode.QUOTA_HIT,
    ApplicationState.DRAFTED_AND_QUEUED: OutcomeCode.QUOTA_HIT,
    ApplicationState.FAILED: OutcomeCode.INFRA_ERROR,
}


def classify(state: ApplicationState | str | None, reason: str | None) -> OutcomeCode:
    """Exactly one outcome code for an adapter/service result.

    Never-replay states win over the reason text: an APPLIED row is APPLIED (unless the portal
    said we had applied before) and a SUBMISSION_UNKNOWN row is always SUBMISSION_UNKNOWN.
    """
    st = ApplicationState(state) if isinstance(state, str) else state
    text = (reason or "").strip().lower()
    if st is ApplicationState.SUBMISSION_UNKNOWN:
        return OutcomeCode.SUBMISSION_UNKNOWN
    for prefix, code in _RULES:
        if text.startswith(prefix):
            if st is ApplicationState.APPLIED and code is not OutcomeCode.ALREADY_APPLIED:
                return OutcomeCode.APPLIED
            return code
    if st is not None and st in _STATE_DEFAULT:
        return _STATE_DEFAULT[st]
    if st is ApplicationState.SCORED and text.startswith("dry_run"):
        return OutcomeCode.DRY_RUN_STOPPED
    return OutcomeCode.FILTERED if st in (None, ApplicationState.DISCOVERED, ApplicationState.SCORED) \
        else OutcomeCode.INFRA_ERROR


def trips_breaker(code: OutcomeCode) -> bool:
    return code in BREAKER_OUTCOMES
