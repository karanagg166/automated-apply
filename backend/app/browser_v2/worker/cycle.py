"""Worker mixin: one rotation cycle (live reload, round-robin, breaker gate, cooldown resumption)."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.browser_v2.outcomes import OutcomeCode
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    PortalRules,
    paused,
    within_active_hours,
)
from backend.app.browser_v2.store import WorkerControl, WorkerState
from backend.app.browser_v2.worker.context import (
    ELAPSED,
    STOPPED,
    WOKEN,
    Circuit,
    CycleContext,
    Turn,
)
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    CycleReport,
    Interrupted,
    PortalReport,
    logger,
)


class CycleMixin(WorkerLoop):
    async def load_context(self, control: WorkerControl, *, run_once: bool,
                           configure: bool = False) -> CycleContext:
        """Live reload: dashboard edits (rules, preferences, circuit resets) apply without a restart."""
        dry_run = self.dry_run(control)
        now = self.clock()
        all_rules = await self.store.list_rules()
        profile = await self.store.load_profile()
        prefs = CandidatePreferences.from_profile(profile[0])
        if configure:
            configure_adapters = getattr(self.service, "configure_adapters", None)
            if configure_adapters is not None:
                await configure_adapters(profile[0])  # Phase 6A: board lists etc. re-read every cycle
        self.load_circuits(all_rules)
        ctx = CycleContext(rules={r.platform: r for r in all_rules}, prefs=prefs, profile=profile,
                           dry_run=dry_run, run_once=run_once,
                           report=CycleReport(started_at=now, dry_run=dry_run),
                           deadline=now + timedelta(seconds=self.cycle_interval_sec))
        self.ctx = ctx
        return ctx

    def load_circuits(self, all_rules: list[PortalRules]) -> None:
        """The persisted breaker state is the source of truth (an owner may reset it in the DB)."""
        for rules in all_rules:
            self.circuits[rules.platform] = Circuit(failures=rules.circuit_failures, level=rules.circuit_level,
                                                    open_until=rules.circuit_open_until,
                                                    reason=rules.circuit_reason)

    async def cycle(self, control: WorkerControl | None = None, *, run_once: bool = False) -> CycleReport:
        control = control or await self.control()
        await self.close_deferred()  # an interrupted cycle's cooldown waits are not resumed
        self.attempted.clear()
        ctx = await self.load_context(control, run_once=run_once, configure=True)
        all_rules = list(ctx.rules.values())
        if all_rules:  # round-robin: this cycle starts where the last one left off
            start = self.rotation % len(all_rules)
            all_rules = all_rules[start:] + all_rules[:start]
            self.rotation += 1
        for rules in all_rules:  # report order == rotation order, even for priority-lane work
            ctx.portal(rules.platform)
        try:
            await self.drain_priority(run_once=run_once)
            for index, rules in enumerate(all_rules):
                if index:
                    await self.housekeeping()  # digest/expiry stay punctual during long cycles
                    await self.between_jobs(ctx, run_once=run_once)
                portal = ctx.portal(rules.platform)
                skipped = self.portal_skip(rules, run_once=run_once)
                if skipped is not None:
                    portal.skipped = skipped
                    continue
                await self.run_turn(rules, portal, dry_run=ctx.dry_run, run_once=run_once)
                if not ctx.dry_run:
                    await self.process_quota(rules, ctx.profile[0], portal)
            await self.finish_deferred(ctx)
        except Interrupted:
            ctx.report.interrupted = True
        return ctx.report

    def portal_skip(self, rules: PortalRules, *, run_once: bool) -> str | None:
        now = self.clock()
        if not rules.enabled:
            return "portal_disabled"
        if rules.platform not in self.service.adapters:
            return "adapter_not_implemented"
        if paused(rules, now):
            return "paused_until"
        if not within_active_hours(rules, now):
            return "outside_active_hours"
        blocked = self.circuit_blocked_until(rules.platform, now)
        if blocked is not None and not run_once:
            return f"circuit_open_until:{blocked.isoformat(timespec='seconds')}"
        return None

    async def run_turn(self, rules: PortalRules, portal: PortalReport, *, dry_run: bool, run_once: bool,
                       turn: Turn | None = None) -> None:
        """A portal turn (or the resumption of one that yielded to a cooldown), isolated: a failing
        portal counts toward its circuit breaker while the others keep running."""
        platform = rules.platform
        ctx = self.ctx
        assert ctx is not None
        self.turn_observed[platform] = 0
        try:
            if turn is None:
                await self.run_portal(rules, ctx.prefs, ctx.profile, portal, dry_run=dry_run, run_once=run_once)
            else:
                await self.drive(turn)
        except Interrupted:
            raise
        except Exception as exc:  # noqa: BLE001 - logs via logger.exception (logger imported from reports)
            logger.exception("portal %s failed", platform)
            portal.errors += 1
            portal.skipped = f"error: {type(exc).__name__}"
            self.deferred.pop(platform, None)
            self.session_ok_at.pop(platform, None)  # the lane/sweeps re-verify before touching it again
            await self.observe(platform, OutcomeCode.INFRA_ERROR, f"portal_error:{type(exc).__name__}")
            return
        if not self.turn_observed.get(platform) and portal.skipped is None and platform not in self.deferred \
                and portal.stopped_reason is None:
            await self.observe(platform, OutcomeCode.FILTERED, None)  # session + discovery worked

    async def finish_deferred(self, ctx: CycleContext) -> None:
        """Resume turns that yielded to an apply cooldown; while every one is cooling down, wait for the
        earliest expiry (or a wake-up, which runs the P0/P1 lane first) - never past the next cycle."""
        while self.deferred:
            if not await self.should_continue(run_once=ctx.run_once):
                raise Interrupted
            now = self.clock()
            runnable = [p for p in list(self.deferred) if self.cooldown_until(p, now) is None]
            if runnable:
                for platform in runnable:
                    turn = self.deferred.pop(platform)
                    await self.run_turn(turn.rules, turn.portal, dry_run=turn.dry_run, run_once=turn.run_once,
                                        turn=turn)
                    await self.between_jobs(ctx, run_once=ctx.run_once)
                continue
            ends = [t for p in self.deferred if (t := self.cooldown_until(p, now)) is not None]
            if self.next_global_apply_at is not None and self.next_global_apply_at > now:
                ends.append(self.next_global_apply_at)  # the lane may run other portals' P0/P1 then
            target = min(ends)
            if target > ctx.deadline:
                for turn in self.deferred.values():
                    turn.portal.stopped_reason = "cooldown_past_cycle"
                await self.close_deferred()
                return
            status, waited = await self.wait((target - now).total_seconds(), run_once=ctx.run_once)
            if status == STOPPED:
                raise Interrupted
            if status == ELAPSED:
                self.expire_cooldowns(now + timedelta(seconds=waited))
            await self.between_jobs(ctx, run_once=ctx.run_once)

    def expire_cooldowns(self, at: datetime) -> None:
        """Cooldowns a completed wait has outlasted (also correct under a frozen test clock)."""
        self.next_apply_at = {p: t for p, t in self.next_apply_at.items() if t > at}
        if self.next_global_apply_at is not None and self.next_global_apply_at <= at:
            self.next_global_apply_at = None

    async def close_deferred(self) -> None:
        deferred, self.deferred = self.deferred, {}
        for turn in deferred.values():
            close = getattr(turn.items, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception as exc:  # noqa: BLE001 - a stale generator never breaks the loop
                    logger.info("closing deferred turn %s: %s", turn.rules.platform, type(exc).__name__)

    async def between_cycles(self) -> None:
        """Wait for the next cycle. A wake-up or a due fresh sweep runs the P0/P1 lane / sweep now and
        then keeps waiting out the interval; a run-once request starts the next cycle at once."""
        started, slept = self.clock(), 0.0
        while True:
            remaining = self.cycle_interval_sec - max(slept, (self.clock() - started).total_seconds())
            if remaining <= 0:
                return
            sweep_in = self.seconds_until_sweep(self.clock())
            span = remaining if sweep_in is None else max(1.0, min(remaining, sweep_in))
            status, waited = await self.wait(span, heartbeat="SLEEPING")
            slept += waited
            if status == STOPPED:
                return
            if status == WOKEN and waited <= 0:
                slept += 1.0  # a burst of wake-ups (or a frozen test clock) can never spin forever
            try:
                control = await self.control()
                if control.run_once_requested_at is not None or control.desired_state is not WorkerState.RUNNING:
                    return
                await self.between_jobs(await self.load_context(control, run_once=False))
            except Interrupted:
                return
            except Exception:  # noqa: BLE001 - between-cycle work must not kill the 24/7 loop
                logger.exception("between-cycle priority/sweep work failed")

    async def between_jobs(self, ctx: CycleContext, *, run_once: bool = False) -> None:
        """Between jobs: P0/P1 first, then any due fresh sweep (which drains what it found)."""
        await self.drain_priority(run_once=run_once)
        await self.maybe_sweep(ctx, run_once=run_once)
