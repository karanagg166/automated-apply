"""Worker mixin: Phase 5 quota-hit dual action (park, draft, notify) and dry-run caps."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from backend.app.browser_v2.quota import QuotaReport, fallback_daily_cap, quota_summary
from backend.app.browser_v2.redact import describe_exception
from backend.app.browser_v2.rules import CandidatePreferences, PortalRules
from backend.app.browser_v2.service import day_start, quota_counts
from backend.app.browser_v2.state import InvalidTransition
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    DISCOVERY_LIMIT,
    QUOTA_INSPECTIONS_PER_CYCLE,
    Interrupted,
    PortalReport,
    S,
    logger,
)


class QuotaFlowMixin(WorkerLoop):
    # --- Phase 5: quota-hit dual action -----------------------------------------------
    async def process_quota(self, rules: PortalRules, profile: dict[str, Any], portal: PortalReport) -> None:
        """Draft once + queue tomorrow for parked jobs; isolated so it never breaks a cycle."""
        try:
            counts = await quota_counts(self.store, rules, self.clock())
            exhausted = bool(counts["daily_limit_hit"] or counts["portal_limit_hit_today"])
            result = await self.quota.process(rules, profile, quota_exhausted=exhausted)
        except Exception as exc:  # noqa: BLE001 - logs via logger.exception (logger imported from reports)
            logger.exception("quota processing failed for %s", rules.platform)
            portal.errors += 1
            portal.outcomes.append({"quota_error": type(exc).__name__})
            return
        portal.drafted += result.drafted
        portal.queued_for_retry += result.queued
        portal.outcomes.extend(result.outcomes)
        if exhausted:
            await self.notify_quota(rules, result)

    async def notify_quota(self, rules: PortalRules, result: QuotaReport) -> None:
        notifier = getattr(self, "notifier", None)
        if (self.notify is None and notifier is None) or not result.queued:
            return
        key = (rules.platform, day_start(rules, self.clock()).isoformat())
        if key in self.notified:
            return  # throttled: one summary per portal per day
        self.notified.add(key)
        text = quota_summary(rules, result.drafted, result.queued, result.retry_after)
        try:
            if notifier is not None:  # routine (P2): digest only, deduped per portal per day (ledger)
                await notifier.notify_text(text, platform=rules.platform)
            elif self.notify is not None:
                await self.notify(text)
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
                                        "error": describe_exception(exc, 300)})
                continue
            if outcome.get("state") == S.QUOTA_HIT_PENDING.value:
                portal.quota_pending += 1
            elif outcome.get("state") == S.FILTERED_OUT.value:
                portal.filtered += 1

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
