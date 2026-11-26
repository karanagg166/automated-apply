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
  MAX_INSPECTIONS_PER_PORTAL jobs per turn. A portal whose turn raises (Playwright/network
  timeout, DOM drift) backs off for 5, 10, 20 .. 60 min (reset on success) while the
  others keep running; 3 consecutive job errors end that portal's turn early.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.adapters.feeds import PortalWallActive
from backend.app.browser_v2.manager import RECYCLE_AFTER_SEC
from backend.app.browser_v2.quota import (
    QUOTA_LIMIT_REASONS,
    Notifier,
    QuotaHitProcessor,
    QuotaReport,
    fallback_daily_cap,
    quota_summary,
)
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    PortalRules,
    paused,
    within_active_hours,
)
from backend.app.browser_v2.service import (
    BrowserService,
    day_start,
    plain,
    quota_counts,
)
from backend.app.browser_v2.state import (
    APPLY_ELIGIBLE,
    ApplicationState,
    InvalidTransition,
)
from backend.app.browser_v2.store import WorkerControl, WorkerState

logger = logging.getLogger(__name__)
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
PORTAL_BACKOFF_BASE_SEC = 5 * 60
PORTAL_BACKOFF_MAX_SEC = 60 * 60
MAX_CONSECUTIVE_JOB_ERRORS = 3


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
    stopped_reason: str | None = None
    outcomes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CycleReport:
    started_at: datetime
    dry_run: bool
    portals: list[PortalReport] = field(default_factory=list)
    interrupted: bool = False


class Interrupted(Exception):
    """Pause/stop requested between jobs."""


class Worker:
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
        # Phase 8: round-robin start + per-portal bounded backoff (failures, retry-at).
        self.rotation = 0
        self.portal_backoff: dict[str, tuple[int, datetime]] = {}
        self.housekeeping_log: list[dict[str, Any]] = []

    # --- control ------------------------------------------------------------------
    async def control(self) -> WorkerControl:
        return await self.store.get_worker_control()

    async def should_continue(self, *, run_once: bool) -> bool:
        if self.stop_event.is_set():
            return False
        if run_once:
            return True
        return (await self.control()).desired_state is WorkerState.RUNNING

    async def sleep(self, seconds: float, *, run_once: bool = False) -> bool:
        """Sleep in short slices; False as soon as pause/stop/SIGTERM is requested."""
        remaining = max(0.0, seconds)
        while remaining > 0:
            if not await self.should_continue(run_once=run_once):
                return False
            chunk = min(remaining, self.idle_poll_sec)
            await self._wait_stop(chunk)
            remaining -= chunk
        return await self.should_continue(run_once=run_once)

    async def _wait_stop(self, seconds: float) -> None:
        if self._sleep is asyncio.sleep:
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
            except TimeoutError:
                pass
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
                    await self.store.worker_heartbeat("RUNNING", last_error=f"{type(exc).__name__}: {exc}",
                                                      clear_run_once=control.run_once_requested_at is not None)
                    if once:
                        raise
                    await self.sleep(ERROR_BACKOFF_SEC)
                    continue
                if once:
                    return reports
                await self.sleep(self.cycle_interval_sec)
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

    async def cycle(self, control: WorkerControl | None = None, *, run_once: bool = False) -> CycleReport:
        control = control or await self.control()
        dry_run = self.dry_run(control)
        report = CycleReport(started_at=self.clock(), dry_run=dry_run)
        # Live reload: dashboard edits take effect here without a restart.
        all_rules = await self.store.list_rules()
        profile = await self.store.load_profile()
        prefs = CandidatePreferences.from_profile(profile[0])
        configure = getattr(self.service, "configure_adapters", None)
        if configure is not None:
            await configure(profile[0])  # Phase 6A: board lists etc. re-read every cycle
        if all_rules:  # round-robin: this cycle starts where the last one left off
            start = self.rotation % len(all_rules)
            all_rules = all_rules[start:] + all_rules[:start]
            self.rotation += 1
        for index, rules in enumerate(all_rules):
            if index:
                await self.housekeeping()  # digest/expiry stay punctual during long cycles
            portal = PortalReport(platform=rules.platform)
            report.portals.append(portal)
            if not rules.enabled:
                portal.skipped = "portal_disabled"
                continue
            if rules.platform not in self.service.adapters:
                portal.skipped = "adapter_not_implemented"
                continue
            if paused(rules, self.clock()):
                portal.skipped = "paused_until"
                continue
            if not within_active_hours(rules, self.clock()):
                portal.skipped = "outside_active_hours"
                continue
            backoff = self.portal_backoff.get(rules.platform)
            if backoff is not None and backoff[1] > self.clock() and not run_once:
                portal.skipped = f"backoff_until:{backoff[1].isoformat(timespec='seconds')}"
                continue
            try:
                await self.run_portal(rules, prefs, profile, portal, dry_run=dry_run, run_once=run_once)
            except Interrupted:
                report.interrupted = True
                break
            except Exception as exc:
                logger.exception("portal %s failed", rules.platform)
                portal.errors += 1
                portal.skipped = f"error: {type(exc).__name__}"
                self.back_off(rules.platform, transient=is_transient(exc))
            else:
                if portal.stopped_reason == "consecutive_errors":
                    self.back_off(rules.platform, transient=True)
                else:
                    self.portal_backoff.pop(rules.platform, None)
            if not dry_run:
                await self.process_quota(rules, profile[0], portal)
        return report

    def back_off(self, platform: str, *, transient: bool) -> datetime:
        """5, 10, 20, 40, 60 min (non-transient errors start at the 20 min step)."""
        failures = self.portal_backoff.get(platform, (0, self.clock()))[0] + (1 if transient else 3)
        delay = min(PORTAL_BACKOFF_MAX_SEC, PORTAL_BACKOFF_BASE_SEC * 2 ** (failures - 1))
        until = self.clock() + timedelta(seconds=delay)
        self.portal_backoff[platform] = (failures, until)
        logger.warning("portal %s backing off %ss (failures=%s)", platform, int(delay), failures)
        return until

    # --- Phase 5: quota-hit dual action -----------------------------------------------
    async def process_quota(self, rules: PortalRules, profile: dict[str, Any], portal: PortalReport) -> None:
        """Draft once + queue tomorrow for parked jobs; isolated so it never breaks a cycle."""
        try:
            counts = await quota_counts(self.store, rules, self.clock())
            exhausted = bool(counts["daily_limit_hit"] or counts["portal_limit_hit_today"])
            result = await self.quota.process(rules, profile, quota_exhausted=exhausted)
        except Exception as exc:
            logger.exception("quota processing failed for %s", rules.platform)
            portal.errors += 1
            portal.outcomes.append({"quota_error": type(exc).__name__})
            return
        portal.drafted += result.drafted
        portal.queued_for_retry += result.queued
        portal.outcomes.extend(result.outcomes)
        if exhausted:
            await self.notify_quota(rules, result)

    # --- Phase 6A: housekeeping (mail watchers + nightly digest) ----------------------------
    async def housekeeping(self) -> None:
        now = self.clock()
        reader = self.mail_reader
        if reader is not None and getattr(reader, "any_configured", False) and (
                self.last_mail_scan is None
                or (now - self.last_mail_scan).total_seconds() >= self.mail_scan_interval_sec):
            self.last_mail_scan = now
            try:
                replies = await reader.scan_recruiter_replies(self.store, notify=self.notify)
                publish = getattr(self.service, "publish", None)
                for alert in replies.alerts:
                    if publish is not None:
                        await publish("mail.recruiter_reply", {"alert": alert[:200]})
                alerts = await reader.scan_job_alert_emails(self.store)
                self.housekeeping_log.append({"mail_scan": now.isoformat(), "replies": replies.new_events,
                                              "alert_jobs": alerts.discovered, "tier": replies.tier})
            except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
                logger.warning("mail watcher failed: %s", type(exc).__name__)
        await self.expire_hitl(now)
        await self.send_digest(now, reader)
        del self.housekeeping_log[:-50]

    async def expire_hitl(self, now: datetime) -> None:
        """Phase 8: stale HITL requests expire (OTP 30 min .. QUESTION 7 days); never blocks."""
        if self.last_hitl_expiry is not None and (now - self.last_hitl_expiry).total_seconds() < HITL_EXPIRY_EVERY_SEC:
            return
        self.last_hitl_expiry = now
        try:
            from backend.app.browser_v2.hitl import HITLResolutionService

            expired = await HITLResolutionService(self.store, clock=self.clock).expire_stale(now)
            if expired:
                self.housekeeping_log.append({"hitl_expired": len(expired)})
        except Exception as exc:  # noqa: BLE001 - never break the 24/7 loop
            logger.warning("hitl expiry failed: %s", type(exc).__name__)

    async def send_digest(self, now: datetime, reader: Any = None) -> None:
        if self.digest is None or self.notify is None:
            return
        try:
            if not await self.digest.due(now):
                return
            claimed, previous = await self.digest.claim(now)
            if not claimed:
                return  # another process/restart already sent today's digest
            from backend.app.browser_v2.digest import build_digest

            try:
                text = await build_digest(self.store, now, ai=getattr(self.service, "ai", None),
                                          mail_events=getattr(reader, "events", None))
                await self.notify(text)
            except Exception:
                await self.digest.release(now, previous)  # retried on the next housekeeping tick
                raise
            await self.digest.mark_sent(now)
            self.housekeeping_log.append({"digest": now.isoformat()})
        except Exception as exc:  # noqa: BLE001
            logger.warning("digest failed: %s", type(exc).__name__)

    async def notify_quota(self, rules: PortalRules, result: QuotaReport) -> None:
        if self.notify is None or not result.queued:
            return
        key = (rules.platform, day_start(rules, self.clock()).isoformat())
        if key in self.notified:
            return  # throttled: one summary per portal per day
        self.notified.add(key)
        try:
            await self.notify(quota_summary(rules, result.drafted, result.queued, result.retry_after))
        except Exception as exc:  # noqa: BLE001 - notifications are best-effort
            logger.warning("quota notification failed: %s", type(exc).__name__)

    async def park_new_candidates(self, rules: PortalRules, prefs: CandidatePreferences,
                                  profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                                  reason: str, *, run_once: bool) -> None:
        """Quota already hit: inspect (never apply) a few fresh discoveries and park the passing ones
        for the draft + next-day retry path. Capped per portal per day (QUOTA_FALLBACK_DAILY_CAP)."""
        platform, now = rules.platform, self.clock()
        cap = fallback_daily_cap(rules)
        today = day_start(rules, now)
        inspections_key = (platform, today.isoformat())
        used = self.quota_inspections.get(inspections_key, 0)
        budget = min(QUOTA_INSPECTIONS_PER_CYCLE, cap - await self.store.parked_since(platform, today),
                     cap * 3 - used)
        if budget <= 0:
            return
        listings = await self.service.discover_listings(platform, self.next_query(platform, prefs),
                                                        DISCOVERY_LIMIT, rules)
        portal.discovered += len(listings)
        inspected = 0
        for listing in listings:
            if inspected >= budget:
                break
            if not await self.should_continue(run_once=run_once):
                raise Interrupted
            existing = await self.store.get(platform, listing.external_job_id)
            if existing is not None and existing.state not in (S.DISCOVERED, S.FAILED):
                continue
            _, verdict = await self.service.prefilter(listing, rules, prefs, record_filters=True)
            if verdict is not None:
                portal.filtered += 1
                continue
            if inspected and not await self.sleep(self.rng.uniform(*self.inspection_pause_sec), run_once=run_once):
                raise Interrupted
            inspected += 1
            self.quota_inspections[inspections_key] = self.quota_inspections.get(inspections_key, 0) + 1
            try:
                outcome = await self.service.process_job(listing, dry_run=True, rules=rules, profile=profile,
                                                         record_filters=True, park_reason=reason)
            except Exception as exc:  # noqa: BLE001 - isolate one job
                portal.errors += 1
                portal.outcomes.append({"external_job_id": listing.external_job_id,
                                        "error": f"{type(exc).__name__}: {exc}"})
                continue
            if outcome.get("state") == S.QUOTA_HIT_PENDING.value:
                portal.quota_pending += 1
            elif outcome.get("state") == S.FILTERED_OUT.value:
                portal.filtered += 1

    # --- portal -------------------------------------------------------------------
    async def run_portal(self, rules: PortalRules, prefs: CandidatePreferences,
                         profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                         *, dry_run: bool, run_once: bool) -> None:
        platform = rules.platform
        await self.store.worker_heartbeat("RUNNING", current_platform=platform)
        if not await self.session_ok(platform, portal):
            return
        await self.reconcile(platform, portal)
        if not dry_run:
            counts = await quota_counts(self.store, rules, self.clock())
            if counts["daily_limit_hit"] or counts["portal_limit_hit_today"]:
                reason = "dashboard_daily_limit" if counts["daily_limit_hit"] else "portal_daily_limit"
                portal.quota_pending += await self.mark_quota_pending(platform, reason)
                portal.skipped = reason
                await self.park_new_candidates(rules, prefs, profile, portal, reason, run_once=run_once)
                return
            if counts["hourly_limit_hit"]:
                portal.skipped = "dashboard_hourly_limit"
                return
        elif self.dry_cap_reached(rules) is not None:
            portal.skipped = "dry_run_" + str(self.dry_cap_reached(rules))
            return
        seen: set[str] = set()
        # Priority re-queue: HITL-resolved jobs run before any new discovery.
        for record in await self.store.requeued_applications(platform, limit=DISCOVERY_LIMIT):
            if not await self.should_continue(run_once=run_once):
                raise Interrupted
            seen.add(record.external_job_id)
            self.inspected_only.discard((platform, record.external_job_id))
            portal.requeued += 1
            try:
                stop = await self.handle_listing(self.backlog_listing(record), rules, prefs, profile, portal,
                                                 dry_run=dry_run, run_once=run_once)
            finally:
                await self.store.mark_hitl_consumed(record.id)
            if stop:
                portal.stopped_reason = stop
                return
        # Phase 5: yesterday's quota-hit jobs whose retry is due run before new discoveries.
        if not dry_run:
            for record in await self.store.due_retries(platform, self.clock(), limit=DISCOVERY_LIMIT):
                if not await self.should_continue(run_once=run_once):
                    raise Interrupted
                seen.add(record.external_job_id)
                try:
                    record = await self.store.transition(record, S.SCORED, "quota_retry_due",
                                                         payload={"retry_after": record.retry_after})
                except InvalidTransition:
                    continue
                portal.retried += 1
                self.inspected_only.discard((platform, record.external_job_id))
                stop = await self.handle_listing(self.backlog_listing(record), rules, prefs, profile, portal,
                                                 dry_run=dry_run, run_once=run_once)
                if stop:
                    portal.stopped_reason = stop
                    return
        portal.query = self.next_query(platform, prefs)
        listings = await self.service.discover_listings(platform, portal.query, DISCOVERY_LIMIT, rules)
        portal.discovered = len(listings)
        backlog = await self.store.list_by_state(platform, BACKLOG_STATES, limit=DISCOVERY_LIMIT)
        # Phase 6A: never-processed DISCOVERED rows (job-alert emails, interrupted cycles), bounded.
        backlog += [r for r in await self.store.list_by_state(platform, (S.DISCOVERED,), limit=ALERT_BACKLOG_PER_CYCLE)
                    if r.job_url]
        candidates: list[JobListing] = []
        for item in [*(self.backlog_listing(r) for r in backlog if r.job_url), *listings]:
            if item.external_job_id not in seen:
                seen.add(item.external_job_id)
                candidates.append(item)
        for listing in candidates:
            if not await self.should_continue(run_once=run_once):
                raise Interrupted
            stop = await self.handle_listing(listing, rules, prefs, profile, portal,
                                             dry_run=dry_run, run_once=run_once)
            if stop:
                portal.stopped_reason = stop
                break
            await self.service.manager.maybe_recycle_between_jobs(RECYCLE_AFTER_SEC)

    async def reconcile(self, platform: str, portal: PortalReport) -> None:
        """Phase 8b: confirm post-click SUBMISSION_UNKNOWN rows from the portal's history (read-only)."""
        reconcile = getattr(self.service, "reconcile_submissions", None)
        if reconcile is None:
            return
        try:
            for row in await reconcile(platform):
                portal.outcomes.append({"reconciled": row})
                if row.get("verified"):
                    portal.applied += 1
        except Exception as exc:  # noqa: BLE001 - verification is best effort, never blocks the portal
            logger.warning("reconcile %s failed: %s", platform, type(exc).__name__)

    async def session_ok(self, platform: str, portal: PortalReport) -> bool:
        session = await self.service.check_portal_session(platform)
        status = session.get("status")
        if status == "OK":
            await self.store.cancel_open_hitl(platform, "AUTH")
            return True
        if status == "AUTH_REQUIRED":
            # Phase 6A: one bounded auto re-login (Keychain / email OTP / trusted Google chip,
            # 30-min cooldown per portal) before asking the owner.
            login: dict[str, Any] | None = None
            if getattr(self.service, "auto_login", None) is not None:
                try:
                    login = await self.service.attempt_auto_login(platform)
                except Exception as exc:  # noqa: BLE001 - fall through to the HITL
                    login = {"ok": False, "reason": f"auto_login_error:{type(exc).__name__}"}
                if login.get("ok"):
                    recheck = await self.service.check_portal_session(platform)
                    if recheck.get("status") == "OK":
                        await self.store.cancel_open_hitl(platform, "AUTH")
                        portal.outcomes.append({"auto_login": login.get("method")})
                        return True
            # Pause only this portal; one OPEN AUTH request until the owner logs in again.
            if not await self.store.open_hitl_exists(platform, "AUTH"):
                name = platform.capitalize()
                await self.store.create_hitl(
                    None, platform, "AUTH",
                    f"[{name}] Session expired — run login-setup & reply /resume {platform}",
                    {"reason": session.get("reason"), "refreshed": session.get("refreshed"),
                     "auto_login": (login or {}).get("reason")})
                publish = getattr(self.service, "publish", None)
                if publish is not None:
                    await publish("portal.auth_required", {"platform": platform, "reason": session.get("reason"),
                                                           "auto_login": (login or {}).get("reason")})
            portal.skipped = "auth_required"
            return False
        portal.skipped = "auth_unknown"
        return False

    async def handle_listing(self, listing: JobListing, rules: PortalRules, prefs: CandidatePreferences,
                             profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                             *, dry_run: bool, run_once: bool) -> str | None:
        """Process one job. Returns a reason to stop this portal, or None to continue."""
        platform, key = rules.platform, (rules.platform, listing.external_job_id)
        if key in self.inspected_only:
            return None
        existing = await self.store.get(platform, listing.external_job_id)
        if existing is not None and existing.state not in APPLY_ELIGIBLE:
            return None  # FILTERED_OUT, WAITING_FOR_USER, APPLYING, APPLIED, SUBMISSION_UNKNOWN
        _, verdict = await self.service.prefilter(listing, rules, prefs, record_filters=True)
        if verdict is not None:
            portal.filtered += 1
            portal.outcomes.append({"external_job_id": listing.external_job_id, "state": "FILTERED_OUT",
                                    "reason": "; ".join(verdict.reasons)})
            return None
        if portal.inspected >= MAX_INSPECTIONS_PER_PORTAL:
            return "inspection_budget"
        live_apply = not dry_run and rules.auto_apply_enabled
        if not dry_run:
            blocked = await self.service.quota_block(platform, rules, self.clock())
            if blocked in QUOTA_LIMIT_REASONS:
                portal.quota_pending += await self.mark_quota_pending(platform, blocked)
                return blocked
            if blocked:
                return blocked
        elif self.dry_cap_reached(rules):
            return "dry_run_" + str(self.dry_cap_reached(rules))
        if portal.inspected and not await self.sleep(self.rng.uniform(*self.inspection_pause_sec),
                                                     run_once=run_once):
            raise Interrupted
        portal.inspected += 1
        try:
            # auto_apply_enabled=false: inspect + score only (stops before the Apply click).
            outcome = await self.service.process_job(listing, dry_run=not live_apply, rules=rules,
                                                     profile=profile, record_filters=True, now=self.clock())
        except PortalWallActive:
            # A feed portal hit its login/challenge wall this cycle: stop it, jobs stay in the backlog.
            portal.outcomes.append({"external_job_id": listing.external_job_id, "stopped": "portal_wall"})
            return "portal_wall"
        except Exception as exc:  # noqa: BLE001 - isolate one job; post-click errors are already SUBMISSION_UNKNOWN
            portal.errors += 1
            portal.consecutive_errors += 1
            portal.outcomes.append({"external_job_id": listing.external_job_id,
                                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            logger.warning("job %s failed: %s", listing.external_job_id, type(exc).__name__)
            if portal.consecutive_errors >= MAX_CONSECUTIVE_JOB_ERRORS:
                return "consecutive_errors"  # likely a portal-wide outage: let the others run
            return None
        portal.consecutive_errors = 0
        if not live_apply:
            self.inspected_only.add(key)
        portal.outcomes.append(plain({k: outcome.get(k) for k in (
            "external_job_id", "title", "company", "state", "reason", "hitl_request_id")}))
        state, reason = outcome.get("state"), str(outcome.get("reason") or "")
        if outcome.get("refused"):
            return None
        if state == S.FILTERED_OUT.value:
            portal.filtered += 1
            return None
        if outcome.get("portal_limit") or reason.startswith("portal_daily_limit"):
            portal.quota_pending += 1 + await self.mark_quota_pending(platform, "portal_daily_limit")
            return "portal_daily_limit"
        if state == S.QUOTA_HIT_PENDING.value:
            return reason or "quota"
        if state == S.WAITING_FOR_USER.value:
            portal.waiting_for_user += 1  # non-blocking: next job continues
            return None
        if reason == "dry_run_stopped_before_apply_click":
            portal.scored += 1
            if dry_run:
                portal.would_apply += 1
                self.dry_applied.setdefault(platform, []).append(self.clock())
            return None
        if state == S.APPLIED.value:
            portal.applied += 1
        if outcome.get("clicked_apply") or state == S.APPLIED.value:
            # Human-like jitter between live applications; cancellable by pause/stop/SIGTERM.
            delay = self.rng.uniform(rules.min_delay_sec, rules.max_delay_sec)
            if not await self.sleep(delay, run_once=run_once):
                raise Interrupted
        return None

    async def mark_quota_pending(self, platform: str, reason: str) -> int:
        """Daily cap reached: park SCORED candidates for Phase 5 (Gmail draft + next-day retry)."""
        moved = 0
        for record in await self.store.list_by_state(platform, (S.SCORED,), limit=200):
            try:
                await self.store.transition(record, S.QUOTA_HIT_PENDING, reason)
                moved += 1
            except InvalidTransition:  # concurrently moved (stale version): leave it
                logger.warning("quota_pending transition skipped for %s", record.external_job_id)
        return moved

    def dry_cap_reached(self, rules: PortalRules) -> str | None:
        now = self.clock()
        stamps = self.dry_applied.get(rules.platform, [])
        if sum(1 for t in stamps if t >= day_start(rules, now)) >= rules.max_applies_per_day:
            return "dashboard_daily_limit"
        if sum(1 for t in stamps if t >= now - timedelta(hours=1)) >= rules.max_applies_per_hour:
            return "dashboard_hourly_limit"
        return None

    def next_query(self, platform: str, prefs: CandidatePreferences) -> str:
        queries = list(prefs.target_roles) or [DEFAULT_QUERY]
        index = self.query_index.get(platform, 0)
        self.query_index[platform] = index + 1
        return queries[index % len(queries)]

    @staticmethod
    def backlog_listing(record: Any) -> JobListing:
        return JobListing(platform=record.platform, external_job_id=record.external_job_id,
                          url=record.job_url or "", title=record.role_title, company=record.company_name)


async def start_telegram(service: BrowserService, stop: asyncio.Event,
                         env_file: str | None = None) -> asyncio.Task[None] | None:
    """Telegram HITL poller + dispatcher as a sibling task (unconfigured -> status only, no task)."""
    from backend.app.ai_v2.router import load_env
    from backend.app.telegram_v2.bot import TelegramBot
    from backend.app.telegram_v2.config import TelegramConfig

    try:
        reader = getattr(service, "mail_reader", None)
        bot = TelegramBot(TelegramConfig.from_env(load_env(env_file)), service.store, ai=service.ai,
                          event_bus=getattr(service, "event_bus", None),
                          mail_events=getattr(reader, "events", None))
        if not bot.config.configured:
            await bot.run(stop)  # records polling_state='unconfigured' and returns
            return None
        return asyncio.create_task(bot.run(stop), name="telegram-hitl")
    except Exception as exc:  # noqa: BLE001 - Telegram must never stop the application worker
        logger.warning("telegram_v2 disabled for this run: %s", type(exc).__name__)
        return None


async def stop_telegram(task: asyncio.Task[None] | None, stop: asyncio.Event, timeout: float = 10.0) -> None:
    if task is None:
        return
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_v2 shutdown: %s", type(exc).__name__)


async def run_worker(*, dry_run: bool, once: bool, env_file: str | None = None,
                     telegram: bool = True) -> list[CycleReport]:
    """CLI entry: Postgres-backed (worker state must persist), SIGTERM-safe."""
    import signal

    from backend.app.browser_v2.service import build_service

    # Live runs need the DB (worker_control persists desired state); a dry run may
    # fall back to memory before migration 004 so the loop can be smoke-tested.
    dry_run = dry_run or env_forces_dry_run()
    service, backend = await build_service(require_db=not dry_run, env_file=env_file)
    if backend != "postgres" and not once:
        raise RuntimeError("worker_requires_postgres: use --once for an in-memory dry run")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.quota import build_quota_processor

    env = load_env(env_file)
    quota = await build_quota_processor(service, env)
    notify, notify_close = quota_notifier(env) if telegram else (None, None)
    from backend.app.browser_v2.digest import DigestScheduler, digest_hour

    worker = Worker(service, force_dry_run=dry_run, stop_event=stop, quota=quota, notify=notify,
                    mail_reader=getattr(service, "mail_reader", None),
                    digest=DigestScheduler(service.store, hour=digest_hour(env)) if notify is not None else None)
    logger.info("worker store=%s dry_run=%s once=%s telegram=%s", backend, worker.force_dry_run, once, telegram)
    telegram_stop = asyncio.Event()
    telegram_task = await start_telegram(service, telegram_stop, env_file) if telegram else None
    try:
        return await worker.run(once=once)
    finally:
        await stop_telegram(telegram_task, telegram_stop)
        if notify_close is not None:
            await notify_close()
        bus = getattr(service, "event_bus", None)
        if bus is not None:
            await bus.close()
        await service.manager.close()
        await service.store.close()


def quota_notifier(env: dict[str, str]) -> tuple[Notifier | None, Callable[[], Awaitable[None]] | None]:
    """Owner-chat summary when a portal hits its daily limit (None when Telegram is unconfigured)."""
    from backend.app.telegram_v2.client import TelegramClient
    from backend.app.telegram_v2.config import TelegramConfig

    config = TelegramConfig.from_env(env)
    if not config.configured or not config.token or config.owner_chat_id is None:
        return None, None
    client = TelegramClient(config.token)
    chat_id: int = config.owner_chat_id

    async def notify(text: str) -> None:
        await client.send_message(chat_id, html.escape(text, quote=False))  # parse_mode=HTML

    return notify, client.aclose
