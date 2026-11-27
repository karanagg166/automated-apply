"""Worker base: shared state (`__init__`), control polling, wake-able sleeps and the main loop."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.app.browser_v2.quota import Notifier, QuotaHitProcessor
from backend.app.browser_v2.redact import describe_exception
from backend.app.browser_v2.rules import CandidatePreferences, PortalRules
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.store import Store, WorkerControl, WorkerState
from backend.app.browser_v2.worker.context import (
    ELAPSED,
    STOPPED,
    WOKEN,
    Circuit,
    CycleContext,
    Turn,
)
from backend.app.browser_v2.worker.reports import (
    CYCLE_INTERVAL_SEC,
    ERROR_BACKOFF_SEC,
    FRESH_SWEEP_HOURLY_BUDGET,
    GLOBAL_APPLY_GAP_SEC,
    HEARTBEAT_EVERY_SEC,
    IDLE_POLL_SEC,
    INSPECTION_PAUSE_SEC,
    MAIL_SCAN_INTERVAL_SEC,
    CycleReport,
    PortalReport,
    env_forces_dry_run,
    logger,
)

if TYPE_CHECKING:
    from backend.app.browser_v2.adapters.base import JobListing
    from backend.app.browser_v2.outcomes import OutcomeCode


class WorkerLoop:
    """State shared by every Worker mixin plus the control loop (run/sleep/wake)."""

    service: BrowserService
    store: Store
    force_dry_run: bool
    stop_event: asyncio.Event
    wake_event: asyncio.Event
    clock: Callable[[], datetime]
    _sleep: Callable[[float], Awaitable[None]]
    rng: random.Random
    cycle_interval_sec: float
    idle_poll_sec: float
    inspection_pause_sec: tuple[float, float]
    quota: QuotaHitProcessor
    notify: Notifier | None
    notified: set[tuple[str, str]]
    mail_reader: Any
    digest: Any
    mail_scan_interval_sec: float
    rotation: int
    ctx: CycleContext | None
    circuits: dict[str, Circuit]
    deferred: dict[str, Turn]
    next_apply_at: dict[str, datetime]
    next_global_apply_at: datetime | None
    turn_observed: dict[str, int]
    attempted: set[tuple[str, str]]
    session_ok_at: dict[str, datetime]
    priority_seen: set[str]
    last_run_once_seen: datetime | None
    wake_reasons: list[str]
    draining: bool
    global_gap_sec: tuple[float, float]
    last_decay: datetime | None
    last_stale_recovery: datetime | None
    notifier: Any  # followup 007: NotificationRouter (None without Telegram)
    sweep_due: dict[str, datetime]
    sweep_loads: dict[str, list[datetime]]
    sweep_query_index: dict[str, int]
    sweep_hourly_budget: int

    if TYPE_CHECKING:  # implemented by the mixins combined in worker.core.Worker
        async def housekeeping(self) -> None: ...

        async def cycle(self, control: WorkerControl | None = None, *,
                        run_once: bool = False) -> CycleReport: ...

        async def load_context(self, control: WorkerControl, *, run_once: bool,
                               configure: bool = False) -> CycleContext: ...

        async def between_jobs(self, ctx: CycleContext, *, run_once: bool = False) -> None: ...

        async def drain_priority(self, *, run_once: bool = False) -> int: ...

        def lane_eligible(self, rules: PortalRules, now: datetime, *, dry_run: bool) -> bool: ...

        def seconds_until_sweep(self, now: datetime) -> float | None: ...

        async def maybe_sweep(self, ctx: CycleContext, *, run_once: bool = False) -> list[str]: ...

        async def control_tick(self, control: WorkerControl) -> bool: ...

        async def between_cycles(self) -> None: ...

        async def observe_outcome(self, platform: str, outcome: dict[str, Any]) -> None: ...

        def note_discovery(self, platform: str) -> None: ...

        def cooldown_until(self, platform: str, now: datetime) -> datetime | None: ...

        def start_cooldown(self, rules: PortalRules) -> None: ...

        def circuit_blocked_until(self, platform: str, now: datetime) -> datetime | None: ...

        async def observe(self, platform: str, code: OutcomeCode, reason: str | None = None) -> None: ...

        async def process_quota(self, rules: PortalRules, profile: dict[str, Any],
                                portal: PortalReport) -> None: ...

        async def run_portal(self, rules: PortalRules, prefs: CandidatePreferences,
                             profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                             *, dry_run: bool, run_once: bool) -> None: ...

        async def drive(self, turn: Turn) -> None: ...

        async def session_ok(self, platform: str, portal: PortalReport) -> bool: ...

        async def handle_listing(self, listing: JobListing, rules: PortalRules, prefs: CandidatePreferences,
                                 profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                                 *, dry_run: bool, run_once: bool, via: str | None = None) -> str | None: ...

        async def park_new_candidates(self, rules: PortalRules, prefs: CandidatePreferences,
                                      profile: tuple[dict[str, Any], list[tuple[str, str]]],
                                      portal: PortalReport, reason: str, *, run_once: bool) -> None: ...

        async def mark_quota_pending(self, platform: str, reason: str) -> int: ...

        def dry_cap_reached(self, rules: PortalRules) -> str | None: ...

        def next_query(self, platform: str, prefs: CandidatePreferences) -> str: ...

        @staticmethod
        def backlog_listing(record: Any) -> JobListing: ...

    def __init__(self, service: BrowserService, *, force_dry_run: bool = False,
                 stop_event: asyncio.Event | None = None,
                 clock: Callable[[], datetime] | None = None,
                 sleeper: Callable[[float], Awaitable[None]] | None = None,
                 rng: random.Random | None = None,
                 cycle_interval_sec: float = CYCLE_INTERVAL_SEC,
                 idle_poll_sec: float = IDLE_POLL_SEC,
                 inspection_pause_sec: tuple[float, float] = INSPECTION_PAUSE_SEC,
                 quota: QuotaHitProcessor | None = None, notify: Notifier | None = None,
                 mail_reader: Any = None, digest: Any = None,
                 mail_scan_interval_sec: float = MAIL_SCAN_INTERVAL_SEC) -> None:
        self.service = service
        self.store = service.store
        self.force_dry_run = force_dry_run or env_forces_dry_run()
        self.stop_event = stop_event or asyncio.Event()
        self.clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleeper or asyncio.sleep
        self.rng = rng or random.Random()
        self.cycle_interval_sec = cycle_interval_sec
        self.idle_poll_sec = idle_poll_sec
        self.inspection_pause_sec = inspection_pause_sec
        self.query_index: dict[str, int] = {}
        # Dry/inspect-only runs never write APPLIED, so caps and "already inspected"
        # are tracked in memory to avoid re-opening the same SCORED jobs every cycle.
        self.dry_applied: dict[str, list[datetime]] = {}
        self.inspected_only: set[tuple[str, str]] = set()
        # Phase 5: without enrichment/mail wiring the processor still queues tomorrow's retry.
        self.quota = quota or QuotaHitProcessor(self.store, clock=self.clock)
        self.notify = notify
        self.notified: set[tuple[str, str]] = set()
        self.quota_inspections: dict[tuple[str, str], int] = {}
        # Phase 6A: read-only mail watchers + nightly digest (both best effort, between jobs only).
        self.mail_reader = mail_reader
        self.digest = digest
        self.mail_scan_interval_sec = mail_scan_interval_sec
        self.last_mail_scan: datetime | None = None
        self.last_hitl_expiry: datetime | None = None
        # Phase 8: round-robin start.
        self.rotation = 0
        self.housekeeping_log: list[dict[str, Any]] = []
        # Phase 9B: wake-ups (watchers, Telegram, control tick), priority lane, per-portal
        # cooldowns, persisted circuit breakers and fresh sweeps.
        self.wake_event = asyncio.Event()
        self.wake_reasons = []
        self.last_run_once_seen = None
        self.priority_seen = set()
        self.ctx = None
        self.draining = False
        self.next_apply_at = {}
        self.next_global_apply_at = None
        self.global_gap_sec = GLOBAL_APPLY_GAP_SEC
        self.deferred = {}
        self.session_ok_at = {}
        self.circuits = {}
        self.turn_observed = {}
        self.attempted = set()  # jobs opened this cycle (never re-opened by the lane in the same cycle)
        self.last_decay = None
        self.last_stale_recovery = None  # None = run on the first housekeeping tick (boot)
        self.notifier = None
        self.sweep_due = {}
        self.sweep_loads = {}
        self.sweep_query_index = {}
        self.sweep_hourly_budget = FRESH_SWEEP_HOURLY_BUDGET
        bus = getattr(service, "event_bus", None)
        if bus is not None and callable(getattr(bus, "subscribe", None)):
            try:  # in-process publishers (agent, watchers) can wake the worker through the bus
                bus.subscribe("worker.wake", self._on_wake_event)
            except Exception as exc:  # noqa: BLE001 - wake-ups are optional
                logger.info("worker.wake subscription unavailable: %s", type(exc).__name__)

    # --- control ------------------------------------------------------------------
    async def control(self) -> WorkerControl:
        return await self.store.get_worker_control()

    async def should_continue(self, *, run_once: bool) -> bool:
        if self.stop_event.is_set():
            return False
        if run_once:
            return True
        return (await self.control()).desired_state is WorkerState.RUNNING

    def wake(self, reason: str = "manual") -> None:
        """Cut the current between-jobs/between-cycles sleep short (never an in-flight job)."""
        self.wake_reasons.append(str(reason)[:80])
        del self.wake_reasons[:-20]
        self.wake_event.set()

    async def _on_wake_event(self, _topic: str, payload: dict[str, Any]) -> None:
        self.wake(f"event:{payload.get('reason') or 'bus'}")

    async def sleep(self, seconds: float, *, run_once: bool = False, heartbeat: str | None = None,
                    wakeable: bool = True) -> bool:
        """Sleep in short slices; False as soon as pause/stop/SIGTERM is requested.

        `heartbeat` (e.g. "SLEEPING" between cycles) is re-reported about once a minute so the
        watchdog never sees a healthy, waiting worker as stale (cycle interval 10 min > 5 min stale).
        Phase 9B: a wake-up (`wake()` or the control tick) returns early with True (continue).
        """
        status, _ = await self.wait(seconds, run_once=run_once, heartbeat=heartbeat, wakeable=wakeable)
        return status != STOPPED

    async def wait(self, seconds: float, *, run_once: bool = False, heartbeat: str | None = None,
                   wakeable: bool = True) -> tuple[str, float]:
        """(ELAPSED | WOKEN | STOPPED, seconds actually waited)."""
        remaining = max(0.0, seconds)
        since_beat = slept = 0.0
        while remaining > 0:
            if self.stop_event.is_set():
                return STOPPED, slept
            control = None if run_once else await self.control()
            if control is not None and control.desired_state is not WorkerState.RUNNING:
                return STOPPED, slept
            if wakeable and await self._wake_due(control):
                return WOKEN, slept
            chunk = min(remaining, self.idle_poll_sec)
            await self._wait_stop(chunk, wakeable=wakeable)
            if wakeable and self.wake_event.is_set():
                self.wake_event.clear()
                return WOKEN, slept
            remaining -= chunk
            slept += chunk
            since_beat += chunk
            if heartbeat and since_beat >= HEARTBEAT_EVERY_SEC and remaining > 0:
                since_beat = 0.0
                try:
                    await self.store.worker_heartbeat(heartbeat)
                except Exception as exc:  # noqa: BLE001 - a missed heartbeat never stops the loop
                    logger.warning("heartbeat failed: %s", type(exc).__name__)
        return (ELAPSED if await self.should_continue(run_once=run_once) else STOPPED), slept

    async def _wake_due(self, control: WorkerControl | None) -> bool:
        if self.wake_event.is_set():
            self.wake_event.clear()
            return True
        return control is not None and await self.control_tick(control)

    async def _wait_stop(self, seconds: float, *, wakeable: bool = False) -> None:
        if self._sleep is asyncio.sleep:
            waiters = [asyncio.ensure_future(self.stop_event.wait())]
            if wakeable:
                waiters.append(asyncio.ensure_future(self.wake_event.wait()))
            try:
                await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiter in waiters:
                    waiter.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
        else:
            await self._sleep(seconds)

    # --- main loop ----------------------------------------------------------------
    async def run(self, *, once: bool = False) -> list[CycleReport]:
        """Loop until SIGTERM. `once=True` runs exactly one cycle now and returns."""
        reports: list[CycleReport] = []
        control = await self.control()
        logger.info("worker boot desired=%s dry_run=%s", control.desired_state, self.dry_run(control))
        while not self.stop_event.is_set():
            control = await self.control()
            run_once = once or control.run_once_requested_at is not None
            if control.run_once_requested_at is not None:
                self.last_run_once_seen = control.run_once_requested_at
            if control.desired_state is WorkerState.RUNNING or run_once:
                try:
                    report = await self.cycle(control, run_once=run_once)
                    reports.append(report)
                    await self.housekeeping()
                    await self.store.worker_heartbeat(
                        "SLEEPING" if not once else "IDLE", cycle_completed=True,
                        clear_run_once=control.run_once_requested_at is not None)
                except Exception as exc:  # one bad cycle must not kill the 24/7 loop
                    logger.exception("worker cycle failed")
                    try:  # last_error reaches the API + Telegram: never raw exception text (URLs/tokens)
                        await self.store.worker_heartbeat(
                            "RUNNING", last_error=describe_exception(exc, 500),
                            clear_run_once=control.run_once_requested_at is not None)
                    except Exception as beat_exc:  # noqa: BLE001 - a DB blip here must not kill the loop
                        logger.warning("heartbeat after a failed cycle failed: %s", type(beat_exc).__name__)
                    publish = getattr(self.service, "publish", None)
                    if publish is not None:  # P1, one alert per fingerprint per 2 h (notification ledger)
                        await publish("system.error", {"fingerprint": type(exc).__name__,
                                                       "detail": describe_exception(exc, 200)})
                    if once:
                        raise
                    await self.sleep(ERROR_BACKOFF_SEC)
                    continue
                if once:
                    return reports
                await self.between_cycles()
                continue
            if control.desired_state is WorkerState.STOPPED and self.service.manager.running:
                await self.service.manager.close()  # STOP frees Brave RAM; PAUSE keeps it warm
            await self.store.worker_heartbeat(control.desired_state.value)
            await self.housekeeping()  # digest + mail watchers still run while paused
            await self.sleep(self.idle_poll_sec, run_once=True)
        await self.store.worker_heartbeat("OFFLINE")
        return reports

    def dry_run(self, control: WorkerControl) -> bool:
        return self.force_dry_run or control.dry_run
