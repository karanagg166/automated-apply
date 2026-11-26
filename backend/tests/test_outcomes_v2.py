"""Phase 9B: every adapter/service reason maps onto exactly one outcome code."""

from __future__ import annotations

import pytest

from backend.app.browser_v2.outcomes import (
    BREAKER_OUTCOMES,
    OutcomeCode,
    classify,
    trips_breaker,
)
from backend.app.browser_v2.state import ApplicationState as S

CASES = [
    (S.APPLIED, "confirmed", OutcomeCode.APPLIED),
    (S.APPLIED, "verified_in_portal_history", OutcomeCode.APPLIED),
    (S.APPLIED, "already_applied_on_portal", OutcomeCode.ALREADY_APPLIED),
    (S.FILTERED_OUT, "job_closed", OutcomeCode.CLOSED_JOB),
    (S.FILTERED_OUT, "ats_posting_closed", OutcomeCode.CLOSED_JOB),
    (S.WAITING_FOR_USER, "portal_login_required", OutcomeCode.AUTH_REQUIRED),
    (S.WAITING_FOR_USER, "portal_captcha", OutcomeCode.CAPTCHA_WALL),
    (S.WAITING_FOR_USER, "portal_cloudflare", OutcomeCode.CAPTCHA_WALL),
    (S.WAITING_FOR_USER, "ats_captcha_before_submit", OutcomeCode.CAPTCHA_WALL),
    (S.QUOTA_HIT_PENDING, "portal_daily_limit", OutcomeCode.QUOTA_HIT),
    (S.QUOTA_HIT_PENDING, "portal_daily_limit_after_click", OutcomeCode.QUOTA_HIT),
    (S.SCORED, "dashboard_hourly_limit", OutcomeCode.QUOTA_HIT),
    (S.DRAFTED_AND_QUEUED, "quota_hit_drafted_and_queued", OutcomeCode.QUOTA_HIT),
    (S.FILTERED_OUT, "ats_handoff:greenhouse:123", OutcomeCode.EXTERNAL_ATS_HANDED_OFF),
    (S.FILTERED_OUT, "external_unsupported_ats:jobs.workday.com", OutcomeCode.EXTERNAL_UNSUPPORTED_ATS),
    (S.FILTERED_OUT, "external_company_site", OutcomeCode.EXTERNAL_UNSUPPORTED_ATS),
    (S.FILTERED_OUT, "external_company_site_after_click", OutcomeCode.EXTERNAL_UNSUPPORTED_ATS),
    (S.SCORED, "dry_run_stopped_before_apply_click", OutcomeCode.DRY_RUN_STOPPED),
    (S.SCORED, "dry_run_stopped_before_submit", OutcomeCode.DRY_RUN_STOPPED),
    (S.WAITING_FOR_USER, "question_requires_owner", OutcomeCode.NEEDS_REVIEW),
    (S.WAITING_FOR_USER, "questionnaire_unsupported_control", OutcomeCode.NEEDS_REVIEW),
    (S.WAITING_FOR_USER, "ats_validation_errors", OutcomeCode.NEEDS_REVIEW),
    (S.FAILED, "apply_control_unsupported_ui", OutcomeCode.NEEDS_REVIEW),
    (S.SUBMISSION_UNKNOWN, "confirmation_ambiguous", OutcomeCode.SUBMISSION_UNKNOWN),
    (S.SUBMISSION_UNKNOWN, "questionnaire_stalled", OutcomeCode.SUBMISSION_UNKNOWN),
    (S.SUBMISSION_UNKNOWN, "challenge_after_apply_click", OutcomeCode.SUBMISSION_UNKNOWN),
    (S.WAITING_FOR_USER, "challenge_after_apply_click", OutcomeCode.CAPTCHA_WALL),
    (S.FAILED, "apply_control_changed", OutcomeCode.DOM_CHANGED),
    (S.FILTERED_OUT, "apply_control_none", OutcomeCode.CLOSED_JOB),
    (S.FAILED, "ats_submit_control_2", OutcomeCode.DOM_CHANGED),
    (S.FAILED, "dry_run_form_not_found", OutcomeCode.DOM_CHANGED),
    (S.FAILED, "consecutive_errors", OutcomeCode.INFRA_ERROR),
    (S.FILTERED_OUT, "duplicate_of: naukri:1 (APPLIED)", OutcomeCode.FILTERED),
    (S.FILTERED_OUT, "experience_above_profile: needs 3-5 yrs, have 0.33", OutcomeCode.FILTERED),
    (S.FAILED, "TimeoutError: page.goto", OutcomeCode.INFRA_ERROR),
    (S.FILTERED_OUT, "quota_retry_expired", OutcomeCode.CLOSED_JOB),
    ("SCORED", None, OutcomeCode.FILTERED),
]


@pytest.mark.parametrize(("state", "reason", "expected"), CASES)
def test_classify(state: S | str, reason: str | None, expected: OutcomeCode) -> None:
    assert classify(state, reason) is expected


def test_never_replay_states_win() -> None:
    assert classify(S.SUBMISSION_UNKNOWN, "confirmed") is OutcomeCode.SUBMISSION_UNKNOWN
    assert classify(S.APPLIED, "apply_control_changed") is OutcomeCode.APPLIED


def test_breaker_set() -> None:
    assert BREAKER_OUTCOMES == {OutcomeCode.INFRA_ERROR, OutcomeCode.DOM_CHANGED, OutcomeCode.CAPTCHA_WALL}
    assert trips_breaker(OutcomeCode.CAPTCHA_WALL) and not trips_breaker(OutcomeCode.AUTH_REQUIRED)
    assert not trips_breaker(OutcomeCode.QUOTA_HIT) and not trips_breaker(OutcomeCode.FILTERED)
