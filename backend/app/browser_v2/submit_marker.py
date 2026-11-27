"""Did this apply ever reach the final Submit click? (Milestone 2 quota accounting.)

A job's apply runs inside `submit_scope()`. Instrumented adapters (`tracks_submit = True`) call
`mark_submit_attempted()` immediately BEFORE the click that may deliver the application. When the
apply then dies (wall-clock timeout, browser crash, SIGTERM), the service can tell a pre-submit hang
(nothing reached the employer: retryable `FAILED`, no daily quota burned) from a failure during/after
the click (`SUBMISSION_UNKNOWN`, never replayed, counted). Adapters that are not instrumented keep
the safe default: any post-reservation failure is `SUBMISSION_UNKNOWN`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

FAILED_TIMEOUT = "FAILED_TIMEOUT"


@dataclass
class SubmitMarker:
    attempted: bool = False
    attempted_at: datetime | None = None
    label: str | None = None


_CURRENT: ContextVar[SubmitMarker | None] = ContextVar("browser_v2_submit_marker", default=None)


@contextmanager
def submit_scope() -> Iterator[SubmitMarker]:
    """A fresh marker for one apply; the caller keeps the object (it survives task cancellation)."""
    marker = SubmitMarker()
    token = _CURRENT.set(marker)
    try:
        yield marker
    finally:
        _CURRENT.reset(token)


def mark_submit_attempted(label: str = "submit") -> None:
    """Call right BEFORE the click that may submit. No-op outside a scope (CLI / tests)."""
    marker = _CURRENT.get()
    if marker is not None and not marker.attempted:
        marker.attempted, marker.attempted_at, marker.label = True, datetime.now(UTC), label[:40]


def submit_attempted() -> bool:
    marker = _CURRENT.get()
    return bool(marker and marker.attempted)


def tracks_submit(adapter: object) -> bool:
    return bool(getattr(adapter, "tracks_submit", False))


def pre_submit_failure_reason(exc: BaseException) -> str:
    return f"{FAILED_TIMEOUT}:pre_submit:{type(exc).__name__}"[:80]
