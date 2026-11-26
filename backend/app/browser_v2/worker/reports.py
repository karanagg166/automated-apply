"""Worker constants, transient-error classification and cycle report dataclasses."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.app.browser_v2.state import ApplicationState

# Same logger name as the pre-split single module (log lines keep their `name`).
logger = logging.getLogger("backend.app.browser_v2.worker")
S = ApplicationState

IDLE_POLL_SEC = 15
CYCLE_INTERVAL_SEC = 10 * 60
DISCOVERY_LIMIT = 20
MAX_INSPECTIONS_PER_PORTAL = 12
INSPECTION_PAUSE_SEC = (3.0, 8.0)
ERROR_BACKOFF_SEC = 60
# QUOTA_HIT_PENDING / DRAFTED_AND_QUEUED are owned by the Phase 5 quota path (draft +
# scheduled retry), never by the plain backlog.
BACKLOG_STATES = (S.SCORED,)
DEFAULT_QUERY = "software engineer"
QUOTA_INSPECTIONS_PER_CYCLE = 5
MAIL_SCAN_INTERVAL_SEC = 15 * 60
ALERT_BACKLOG_PER_CYCLE = 5  # DISCOVERED jobs (e.g. from job-alert emails) processed per portal cycle
HITL_EXPIRY_EVERY_SEC = 15 * 60
HEARTBEAT_EVERY_SEC = 60
MAX_CONSECUTIVE_JOB_ERRORS = 3
# --- Phase 9B scheduler: priority lane, wake-ups, cooldowns, circuit breaker, fresh sweeps ---------
PRIORITY_DRAIN_MAX = 5  # P0/P1 jobs per drain, so the normal rotation still progresses
PRIORITY_TICK_LIMIT = 5  # rows the 15 s control tick peeks at for a cross-process wake-up
GLOBAL_APPLY_GAP_SEC = (10.0, 20.0)  # random minimum gap between ANY two live applies
SESSION_TRUST_SEC = 10 * 60  # a portal session verified OK this recently is not re-checked by the lane
COOLDOWN = "cooldown"  # handle_listing: portal cooling down after a live apply (job deferred, not dropped)
CIRCUIT_TRIP_AFTER = 3  # consecutive breaker outcomes / portal-level exceptions
CIRCUIT_OPEN_SEC = (15 * 60, 30 * 60, 60 * 60)  # level 1, 2, 3+ (cap)
DECAY_EVERY_SEC = 10 * 60
FRESH_SWEEP_PLATFORMS = ("naukri", "instahyre", "internshala", "wellfound", "work_at_a_startup")
FRESH_SWEEP_EVERY_SEC = 20 * 60
FRESH_SWEEP_JITTER = 0.2  # +- 20 %
FRESH_SWEEP_LIMIT = 20  # page 1 only
FRESH_SWEEP_HOURLY_BUDGET = 6  # sweep page loads per portal per rolling hour
FRESH_SWEEP_BLOCKED_RETRY_SEC = 60  # P0/P1 waiting: look again after the lane had its turn


def is_transient(exc: BaseException) -> bool:
    """Playwright/httpx/network/timeouts: retry the portal later rather than poisoning the run."""
    module = type(exc).__module__ or ""
    return isinstance(exc, (TimeoutError, ConnectionError, OSError)) or module.startswith(
        ("playwright", "httpx", "httpcore"))


def env_forces_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PortalReport:
    platform: str
    skipped: str | None = None
    query: str | None = None
    discovered: int = 0
    filtered: int = 0
    inspected: int = 0
    scored: int = 0
    applied: int = 0
    would_apply: int = 0
    waiting_for_user: int = 0
    requeued: int = 0
    retried: int = 0
    quota_pending: int = 0
    drafted: int = 0
    queued_for_retry: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    priority: int = 0  # Phase 9B: jobs run through the P0/P1 priority lane
    deferred: int = 0  # Phase 9B: times the turn yielded to an apply cooldown
    stopped_reason: str | None = None
    outcomes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CycleReport:
    started_at: datetime
    dry_run: bool
    portals: list[PortalReport] = field(default_factory=list)
    interrupted: bool = False
    swept: list[str] = field(default_factory=list)  # Phase 9B: fresh sweeps run during the cycle


class Interrupted(Exception):
    """Pause/stop requested between jobs."""
