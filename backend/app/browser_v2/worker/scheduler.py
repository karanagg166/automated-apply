"""Worker mixin: Phase 9B early-bird priority lane and per-portal / global apply cooldowns.

P0/P1 rows (`store.priority_candidates`) are drained at the start of every cycle, between portals
and after every job, through the same single-tab `handle_listing` path and the same gates
(enabled, auto-apply or dry-run, active hours, not paused, breaker closed, no cooldown, session,
quota). A drain runs at most PRIORITY_DRAIN_MAX jobs so the normal rotation still progresses.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.browser_v2.rules import PortalRules, paused, within_active_hours
from backend.app.browser_v2.store import ApplicationRecord, WorkerControl
from backend.app.browser_v2.worker.context import CycleContext
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    COOLDOWN,
    PRIORITY_DRAIN_MAX,
    PRIORITY_TICK_LIMIT,
    SESSION_TRUST_SEC,
    Interrupted,
    logger,
)


class SchedulerMixin(WorkerLoop):
    # --- cooldowns ------------------------------------------------------------------
    def cooldown_until(self, platform: str, now: datetime) -> datetime | None:
        """When `platform` may next click Apply (per-portal jitter AND the global minimum gap)."""
        times = [t for t in (self.next_apply_at.get(platform), self.next_global_apply_at)
                 if t is not None and t > now]
        return max(times) if times else None

    def start_cooldown(self, rules: PortalRules) -> None:
        """After a live click/APPLIED: human-like per-portal jitter + a 10-20 s gap before ANY apply.
        The portal is skipped (not slept on) until then, so other portals keep working."""
        now = self.clock()
        delay = self.rng.uniform(rules.min_delay_sec, rules.max_delay_sec)
        self.next_apply_at[rules.platform] = now + timedelta(seconds=delay)
        self.next_global_apply_at = now + timedelta(seconds=self.rng.uniform(*self.global_gap_sec))

    # --- cross-process wake-ups ---------------------------------------------------------
    async def control_tick(self, control: WorkerControl) -> bool:
        """Cross-process wake (API/MCP/CLI): a new run-once request or a new P0/P1 row."""
        requested = control.run_once_requested_at
        if requested is not None and requested != self.last_run_once_seen:
            self.last_run_once_seen = requested
            self.wake_reasons.append("run_once")
            return True
        ctx = self.ctx
        if ctx is None:
            return False
        now = self.clock()
        platforms = [p for p, r in ctx.rules.items() if self.lane_eligible(r, now, dry_run=ctx.dry_run)]
        if not platforms:
            return False
        try:
            rows = await self.store.priority_candidates(now, max_priority=1, platforms=platforms,
                                                        limit=PRIORITY_TICK_LIMIT)
        except Exception as exc:  # noqa: BLE001 - the tick is an optimisation, never fatal
            logger.warning("priority tick failed: %s", type(exc).__name__)
            return False
        fresh = [r.id for r in rows if r.id not in self.priority_seen]
        if not fresh:
            return False
        if len(self.priority_seen) > 500:
            self.priority_seen.clear()
        self.priority_seen.update(fresh)
        self.wake_reasons.append("priority_candidates")
        return True

    # --- priority lane ------------------------------------------------------------------
    def lane_eligible(self, rules: PortalRules, now: datetime, *, dry_run: bool) -> bool:
        """Cheap in-memory gates (session and quota are checked per drain)."""
        if not rules.enabled or rules.platform not in self.service.adapters:
            return False
        if paused(rules, now) or not within_active_hours(rules, now):
            return False
        if not dry_run and not rules.auto_apply_enabled:
            return False
        if self.circuit_blocked_until(rules.platform, now) is not None:
            return False
        return dry_run or self.cooldown_until(rules.platform, now) is None

    def session_trusted(self, platform: str, now: datetime, *, within: float = SESSION_TRUST_SEC) -> bool:
        verified = self.session_ok_at.get(platform)
        return verified is not None and (now - verified).total_seconds() < within

    async def lane_gates_ok(self, rules: PortalRules, ctx: CycleContext) -> bool:
        platform = rules.platform
        if ctx.dry_run:
            if self.dry_cap_reached(rules) is not None:
                return False
        elif await self.service.quota_block(platform, rules, self.clock()):
            return False
        if self.session_trusted(platform, self.clock()):
            return True
        return await self.session_ok(platform, ctx.portal(platform))

    def pushed_back(self) -> set[tuple[str, str]]:
        return {(p, t.pushback.listing.external_job_id) for p, t in self.deferred.items() if t.pushback is not None}

    async def drain_priority(self, *, run_once: bool = False) -> int:
        """Run up to PRIORITY_DRAIN_MAX waiting P0/P1 jobs for eligible portals; returns jobs run."""
        ctx = self.ctx
        if ctx is None or self.draining:
            return 0
        now = self.clock()
        platforms = [p for p, r in ctx.rules.items() if self.lane_eligible(r, now, dry_run=ctx.dry_run)]
        if not platforms:
            return 0
        try:
            rows = await self.store.priority_candidates(now, max_priority=1, platforms=platforms,
                                                        limit=PRIORITY_DRAIN_MAX * 2)
        except Exception as exc:  # noqa: BLE001 - the lane is best effort; the rotation still runs
            logger.warning("priority lane query failed: %s", type(exc).__name__)
            return 0
        ran, blocked, checked = 0, set(), set()
        skip = self.pushed_back() | self.inspected_only
        self.draining = True
        try:
            for record in rows:
                platform = record.platform
                if ran >= PRIORITY_DRAIN_MAX or platform in blocked:
                    continue
                if (platform, record.external_job_id) in skip:
                    continue
                rules = ctx.rules[platform]
                if not self.lane_eligible(rules, self.clock(), dry_run=ctx.dry_run):
                    continue  # e.g. a previous lane job started this portal's cooldown
                if platform not in checked:
                    checked.add(platform)
                    if not await self.lane_gates_ok(rules, ctx):
                        blocked.add(platform)
                        continue
                if not await self.should_continue(run_once=run_once):
                    raise Interrupted
                stop = await self.run_lane_job(record, rules, ctx, run_once=run_once)
                ran += 1
                if stop:
                    blocked.add(platform)  # quota/budget/cooldown/wall: the rest waits for its turn
                if self.circuit_blocked_until(platform, self.clock()) is not None:
                    blocked.add(platform)
        finally:
            self.draining = False
        return ran

    async def run_lane_job(self, record: ApplicationRecord, rules: PortalRules, ctx: CycleContext, *,
                           run_once: bool) -> str | None:
        platform = record.platform
        portal = ctx.portal(platform)
        await self.store.worker_heartbeat("RUNNING", current_platform=platform)
        # An owner-answered HITL row is a priority re-queue: count it and consume the answers after.
        answers = await self.store.hitl_answers(record.id)
        if answers:
            self.inspected_only.discard((platform, record.external_job_id))
            portal.requeued += 1
        portal.priority += 1
        stop: str | None = None
        try:
            stop = await self.handle_listing(self.backlog_listing(record), rules, ctx.prefs, ctx.profile, portal,
                                             dry_run=ctx.dry_run, run_once=run_once, via="priority")
        finally:
            if answers and stop != COOLDOWN:
                await self.store.mark_hitl_consumed(record.id)
        logger.info("priority lane %s %s P%s -> %s", platform, record.external_job_id, record.priority,
                    stop or "done")
        return stop
