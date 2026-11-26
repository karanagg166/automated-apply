"""Idempotent application state machine with the never-replay guardrail."""

from __future__ import annotations

from enum import StrEnum


class ApplicationState(StrEnum):
    DISCOVERED = "DISCOVERED"
    FILTERED_OUT = "FILTERED_OUT"
    SCORED = "SCORED"
    APPLYING = "APPLYING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    APPLIED = "APPLIED"
    QUOTA_HIT_PENDING = "QUOTA_HIT_PENDING"
    DRAFTED_AND_QUEUED = "DRAFTED_AND_QUEUED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    FAILED = "FAILED"


S = ApplicationState

# Terminal for automation: an Apply may already have reached the employer.
NEVER_REPLAY = frozenset({S.APPLIED, S.SUBMISSION_UNKNOWN})

# States from which an automatic apply may start. WAITING_FOR_USER resumes only
# through the HITL path (Phase 4: an owner answer moves it back to SCORED, a skip
# to FILTERED_OUT); APPLYING means a previous run was interrupted mid-flight and
# must be reconciled, never blindly retried.
APPLY_ELIGIBLE = frozenset({S.DISCOVERED, S.SCORED, S.QUOTA_HIT_PENDING, S.DRAFTED_AND_QUEUED,
                            S.FAILED})

TRANSITIONS: dict[ApplicationState, frozenset[ApplicationState]] = {
    S.DISCOVERED: frozenset({S.FILTERED_OUT, S.SCORED, S.APPLYING, S.FAILED}),
    S.SCORED: frozenset({S.FILTERED_OUT, S.APPLYING, S.QUOTA_HIT_PENDING, S.FAILED}),
    S.FILTERED_OUT: frozenset({S.SCORED}),
    S.APPLYING: frozenset({S.APPLIED, S.SUBMISSION_UNKNOWN, S.WAITING_FOR_USER,
                           S.QUOTA_HIT_PENDING, S.FILTERED_OUT, S.FAILED}),
    S.WAITING_FOR_USER: frozenset({S.APPLYING, S.SCORED, S.FILTERED_OUT, S.SUBMISSION_UNKNOWN, S.FAILED}),
    S.QUOTA_HIT_PENDING: frozenset({S.DRAFTED_AND_QUEUED, S.APPLYING, S.FILTERED_OUT}),
    # Phase 5: the next-day retry re-scores a due job (retry_after <= now) before it
    # applies again; a second quota hit re-parks it without drafting a second email.
    S.DRAFTED_AND_QUEUED: frozenset({S.SCORED, S.APPLYING, S.FILTERED_OUT}),
    S.FAILED: frozenset({S.APPLYING, S.FILTERED_OUT, S.SCORED}),
    S.APPLIED: frozenset(),
    # Phase 8b: reconciliation ONLY - a post-click crash (e.g. a navigation) leaves SUBMISSION_UNKNOWN;
    # when the portal's own application history shows exactly one matching "Application sent", the row
    # becomes APPLIED with that receipt. Both states stay never-replay; nothing ever re-applies.
    S.SUBMISSION_UNKNOWN: frozenset({S.APPLIED}),
}
RECONCILE_REASON = "verified_in_portal_history"


class ReplayRefused(RuntimeError):
    """Raised when automation would repeat a possibly-delivered application."""


class InvalidTransition(RuntimeError):
    pass


def guard_apply(current: ApplicationState | str | None) -> None:
    """Refuse to start an apply for a job that may already have been submitted."""
    if current is None:
        return
    state = ApplicationState(current)
    if state in NEVER_REPLAY:
        raise ReplayRefused(f"never_replay:{state.value}")
    if state not in APPLY_ELIGIBLE:
        raise ReplayRefused(f"not_apply_eligible:{state.value}")


def check_transition(current: ApplicationState | str | None, target: ApplicationState | str) -> None:
    target_state = ApplicationState(target)
    if current is None:
        return
    state = ApplicationState(current)
    if state == target_state:
        return
    if target_state not in TRANSITIONS[state]:
        raise InvalidTransition(f"{state.value}->{target_state.value}")
