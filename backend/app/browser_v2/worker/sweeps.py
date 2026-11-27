"""Worker mixin: Phase 9B browser fresh sweeps for the interactive portals.

Page-1-only discovery (FRESH_SWEEP_LIMIT, freshest results where the adapter supports it) with a
rotating role query, every FRESH_SWEEP_EVERY_SEC +- 20 % per portal within active hours, recorded
with `store.record_fresh_sweep`. Sweeps run only between jobs, never while P0/P1 rows are waiting,
only for portals whose session was verified recently, and within a per-portal hourly page-load
budget. Listings are scored and queued through `prefilter`; the priority lane then runs the P0/P1.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from backend.app.browser_v2.outcomes import OutcomeCode
from backend.app.browser_v2.priority import cadence_factor
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import APPLY_ELIGIBLE
from backend.app.browser_v2.worker.context import CycleContext
from backend.app.browser_v2.worker.reports import (
    DEFAULT_QUERY,
    FRESH_SWEEP_BLOCKED_RETRY_SEC,
    FRESH_SWEEP_EVERY_SEC,
    FRESH_SWEEP_JITTER,
    FRESH_SWEEP_LIMIT,
    FRESH_SWEEP_PLATFORMS,
    Interrupted,
    logger,
)
from backend.app.browser_v2.worker.scheduler import SchedulerMixin

HOUR = timedelta(hours=1)
SWEEP_SESSION_TRUST_SEC = 30 * 60  # sweeps never pay for an extra session-check page load


class SweepMixin(SchedulerMixin):
    def sweep_interval(self) -> timedelta:
        # Adaptive: every ~10 min in IST hiring hours (within the 6 loads/h budget), ~30 min overnight.
        base = FRESH_SWEEP_EVERY_SEC * cadence_factor(self.clock(), peak=0.5, off_peak=1.5)
        return timedelta(seconds=base * self.rng.uniform(1 - FRESH_SWEEP_JITTER,
                                                                           1 + FRESH_SWEEP_JITTER))

    def note_discovery(self, platform: str) -> None:
        """A rotation turn just loaded this portal's search page: the next sweep can wait."""
        if platform in FRESH_SWEEP_PLATFORMS:
            self.sweep_due[platform] = self.clock() + self.sweep_interval()

    def sweep_due_at(self, rules: PortalRules, now: datetime) -> datetime:
        platform = rules.platform
        due = self.sweep_due.get(platform)
        if due is None:
            last = rules.last_fresh_sweep_at
            due = self.sweep_due[platform] = last + self.sweep_interval() if last is not None else now
        loads = self.sweep_loads[platform] = [t for t in self.sweep_loads.get(platform, []) if now - t < HOUR]
        if len(loads) >= self.sweep_hourly_budget:
            due = max(due, loads[-self.sweep_hourly_budget] + HOUR)
        return due

    def sweep_portals(self, now: datetime) -> list[PortalRules]:
        """Interactive portals a sweep could run on right now (cheap, in-memory gates)."""
        ctx = self.ctx
        if ctx is None:
            return []
        return [r for p, r in ctx.rules.items()
                if p in FRESH_SWEEP_PLATFORMS and self.session_trusted(p, now, within=SWEEP_SESSION_TRUST_SEC)
                and self.lane_eligible(r, now, dry_run=True)  # dry_run=True: a cooldown never blocks a sweep
                and (ctx.dry_run or r.auto_apply_enabled)]

    def seconds_until_sweep(self, now: datetime) -> float | None:
        dues = [self.sweep_due_at(r, now) for r in self.sweep_portals(now)]
        return max(0.0, (min(dues) - now).total_seconds()) if dues else None

    async def maybe_sweep(self, ctx: CycleContext, *, run_once: bool = False) -> list[str]:
        now = self.clock()
        due = [r for r in self.sweep_portals(now) if self.sweep_due_at(r, now) <= now]
        if not due:
            return []
        eligible = [p for p, r in ctx.rules.items() if self.lane_eligible(r, now, dry_run=ctx.dry_run)]
        try:
            waiting = eligible and await self.store.priority_candidates(now, max_priority=1, platforms=eligible,
                                                                        limit=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweep priority check failed: %s", type(exc).__name__)
            waiting = []
        if waiting:  # never sweep while P0/P1 jobs wait: the lane goes first
            for rules in due:
                self.sweep_due[rules.platform] = now + timedelta(seconds=FRESH_SWEEP_BLOCKED_RETRY_SEC)
            return []
        swept: list[str] = []
        for rules in due:
            if not await self.should_continue(run_once=run_once):
                raise Interrupted
            if await self.fresh_sweep(rules, ctx):
                swept.append(rules.platform)
        if swept:
            ctx.report.swept.extend(swept)
            await self.drain_priority(run_once=run_once)
        return swept

    def next_sweep_query(self, platform: str, roles: tuple[str, ...]) -> str:
        queries = list(roles) or [DEFAULT_QUERY]
        index = self.sweep_query_index.get(platform, 0)
        self.sweep_query_index[platform] = index + 1
        return queries[index % len(queries)]

    async def fresh_sweep(self, rules: PortalRules, ctx: CycleContext) -> bool:
        platform, now = rules.platform, self.clock()
        self.sweep_due[platform] = now + self.sweep_interval()
        if not ctx.dry_run and await self.service.quota_block(platform, rules, now):
            return False  # nothing a sweep finds could be applied to today
        self.sweep_loads.setdefault(platform, []).append(now)
        query = self.next_sweep_query(platform, tuple(ctx.prefs.target_roles))
        baseline = rules.last_fresh_sweep_at is not None
        try:
            listings = await self.service.discover_listings(platform, query, FRESH_SWEEP_LIMIT,
                                                            replace(rules, max_job_age_days=1), newest_first=True)
        except Exception as exc:  # noqa: BLE001 - a failing sweep counts toward the breaker, never the loop
            logger.warning("fresh sweep %s failed: %s", platform, type(exc).__name__)
            await self.observe(platform, OutcomeCode.INFRA_ERROR, f"sweep_error:{type(exc).__name__}")
            return False
        queued = 0
        for listing in listings:
            existing = await self.store.get(platform, listing.external_job_id)
            if existing is not None and existing.state not in APPLY_ELIGIBLE:
                continue
            _, verdict = await self.service.prefilter(listing, rules, ctx.prefs, record_filters=True,
                                                      via=f"sweep:{platform}", newly_seen=baseline and existing is None,
                                                      now=now)
            queued += verdict is None
        try:
            await self.store.record_fresh_sweep(platform, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("record_fresh_sweep %s failed: %s", platform, type(exc).__name__)
        ctx.rules[platform] = replace(rules, last_fresh_sweep_at=now)
        logger.info("fresh sweep %s query=%r found=%s queued=%s", platform, query, len(listings), queued)
        return True
