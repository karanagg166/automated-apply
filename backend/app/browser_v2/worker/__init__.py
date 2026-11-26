"""Crash-safe, single-tab 24/7 asyncio worker loop (Phase 2).

- Desired state (RUNNING | PAUSED | STOPPED) lives in public.worker_control, so a
  restarted process resumes RUNNING without a dashboard click.
- portal_rules and candidate preferences are re-read at the start of every
  cycle: dashboard edits apply on the next cycle with no restart.
- Per portal: active hours -> session check (AUTH_REQUIRED pauses only that
  portal + one OPEN AUTH HITL row) -> quota gate (daily cap marks SCORED jobs
  QUOTA_HIT_PENDING) -> discover -> card prefilter -> inspect/filter/apply.
- A job needing a human becomes WAITING_FOR_USER and the loop moves on.
- Phase 4: jobs the owner resolved via Telegram/dashboard (SCORED, retry_after
  <= now, unconsumed ANSWERED HITL row) run first in each portal cycle, before
  new discoveries; the Telegram poller/dispatcher runs as a sibling task.
- Phase 5: when a daily cap is hit (dashboard or portal), passing jobs are parked
  QUOTA_HIT_PENDING (plus a small, capped inspect-only pass over new discoveries);
  the QuotaHitProcessor drafts ONE Gmail email per job and queues tomorrow's retry
  (DRAFTED_AND_QUEUED). Due retries run right after HITL re-queues and before new
  discoveries. A throttled Telegram summary (once per portal per day) is optional.
- Stop/pause are honoured only between jobs and during sleeps, never
  mid-submission. Brave is recycled every 3 hours between jobs.
- Phase 8 fairness: each cycle starts at the next portal (round-robin rotation), so a
  slow or interrupted portal never starves the ones after it; every portal is capped at
  MAX_INSPECTIONS_PER_PORTAL jobs per turn; 3 consecutive job errors end that portal's turn early.
- Phase 9B scheduling: P0/P1 early-bird rows run through a bounded priority lane at the start of
  every cycle, between portals and after every job (same gates, same single tab). `Worker.wake()`
  (watchers, Telegram) or the 15 s control tick (API/MCP/CLI: run-once or a new P0/P1 row) cuts a
  between-jobs/between-cycles sleep short - never an in-flight job. After a live apply the portal
  cools down (min/max_delay_sec jitter, plus a 10-20 s global gap between any two applies) while
  other portals keep working. A persisted per-portal circuit breaker (3 consecutive infra/DOM/wall
  outcomes or portal errors -> open 15/30/60 min, half-open single trial) replaces the in-memory
  back-off. Housekeeping decays stale tiers every 10 min; the interactive portals get page-1 fresh
  sweeps every 20 min +- 20 % within an hourly page-load budget.
"""

from __future__ import annotations

from backend.app.browser_v2.worker.breaker import (
    CircuitMixin,
    circuit_open_seconds,
    outcome_code,
)
from backend.app.browser_v2.worker.context import Circuit, CycleContext, Turn, WorkItem
from backend.app.browser_v2.worker.core import Worker
from backend.app.browser_v2.worker.cycle import CycleMixin
from backend.app.browser_v2.worker.executor import ExecutorMixin
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.maintenance import MaintenanceMixin
from backend.app.browser_v2.worker.quota_flow import QuotaFlowMixin
from backend.app.browser_v2.worker.reports import (
    ALERT_BACKLOG_PER_CYCLE,
    BACKLOG_STATES,
    CIRCUIT_OPEN_SEC,
    CIRCUIT_TRIP_AFTER,
    COOLDOWN,
    CYCLE_INTERVAL_SEC,
    DECAY_EVERY_SEC,
    DEFAULT_QUERY,
    DISCOVERY_LIMIT,
    ERROR_BACKOFF_SEC,
    FRESH_SWEEP_EVERY_SEC,
    FRESH_SWEEP_HOURLY_BUDGET,
    FRESH_SWEEP_LIMIT,
    FRESH_SWEEP_PLATFORMS,
    GLOBAL_APPLY_GAP_SEC,
    HEARTBEAT_EVERY_SEC,
    HITL_EXPIRY_EVERY_SEC,
    IDLE_POLL_SEC,
    INSPECTION_PAUSE_SEC,
    MAIL_SCAN_INTERVAL_SEC,
    MAX_CONSECUTIVE_JOB_ERRORS,
    MAX_INSPECTIONS_PER_PORTAL,
    PRIORITY_DRAIN_MAX,
    QUOTA_INSPECTIONS_PER_CYCLE,
    CycleReport,
    Interrupted,
    PortalReport,
    S,
    env_forces_dry_run,
    is_transient,
    logger,
)
from backend.app.browser_v2.worker.runtime import (
    quota_notifier,
    run_worker,
    start_telegram,
    stop_telegram,
)
from backend.app.browser_v2.worker.scheduler import SchedulerMixin
from backend.app.browser_v2.worker.sweeps import SweepMixin

__all__ = [
    "ALERT_BACKLOG_PER_CYCLE",
    "BACKLOG_STATES",
    "CIRCUIT_OPEN_SEC",
    "CIRCUIT_TRIP_AFTER",
    "COOLDOWN",
    "CYCLE_INTERVAL_SEC",
    "DECAY_EVERY_SEC",
    "DEFAULT_QUERY",
    "DISCOVERY_LIMIT",
    "ERROR_BACKOFF_SEC",
    "FRESH_SWEEP_EVERY_SEC",
    "FRESH_SWEEP_HOURLY_BUDGET",
    "FRESH_SWEEP_LIMIT",
    "FRESH_SWEEP_PLATFORMS",
    "GLOBAL_APPLY_GAP_SEC",
    "HEARTBEAT_EVERY_SEC",
    "HITL_EXPIRY_EVERY_SEC",
    "IDLE_POLL_SEC",
    "INSPECTION_PAUSE_SEC",
    "MAIL_SCAN_INTERVAL_SEC",
    "MAX_CONSECUTIVE_JOB_ERRORS",
    "MAX_INSPECTIONS_PER_PORTAL",
    "PRIORITY_DRAIN_MAX",
    "QUOTA_INSPECTIONS_PER_CYCLE",
    "Circuit",
    "CircuitMixin",
    "CycleContext",
    "CycleMixin",
    "CycleReport",
    "ExecutorMixin",
    "Interrupted",
    "MaintenanceMixin",
    "PortalReport",
    "QuotaFlowMixin",
    "S",
    "SchedulerMixin",
    "SweepMixin",
    "Turn",
    "WorkItem",
    "Worker",
    "WorkerLoop",
    "circuit_open_seconds",
    "env_forces_dry_run",
    "is_transient",
    "logger",
    "outcome_code",
    "quota_notifier",
    "run_worker",
    "start_telegram",
    "stop_telegram",
]
