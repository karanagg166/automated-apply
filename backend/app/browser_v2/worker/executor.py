"""Worker mixin: one portal turn (session, reconcile, re-queues, retries, discovery, per-job apply)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.adapters.feeds import PortalWallActive
from backend.app.browser_v2.manager import RECYCLE_AFTER_SEC
from backend.app.browser_v2.outcomes import OutcomeCode
from backend.app.browser_v2.quota import QUOTA_LIMIT_REASONS
from backend.app.browser_v2.rules import CandidatePreferences, PortalRules
from backend.app.browser_v2.service import plain, quota_counts
from backend.app.browser_v2.state import APPLY_ELIGIBLE, InvalidTransition
from backend.app.browser_v2.worker.context import Turn, WorkItem
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    ALERT_BACKLOG_PER_CYCLE,
    BACKLOG_STATES,
    COOLDOWN,
    DEFAULT_QUERY,
    DISCOVERY_LIMIT,
    MAX_CONSECUTIVE_JOB_ERRORS,
    MAX_INSPECTIONS_PER_PORTAL,
    Interrupted,
    PortalReport,
    S,
    logger,
)


class ExecutorMixin(WorkerLoop):
    # --- portal -------------------------------------------------------------------
    async def run_portal(self, rules: PortalRules, prefs: CandidatePreferences,
                         profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                         *, dry_run: bool, run_once: bool) -> None:
        """One portal turn. Jobs are pulled lazily from `portal_items`; a job that meets the portal's
        apply cooldown parks the turn in `self.deferred` (resumed later this cycle), never a sleep."""
        items = self.portal_items(rules, prefs, profile, portal, dry_run=dry_run, run_once=run_once)
        await self.drive(Turn(rules=rules, prefs=prefs, profile=profile, portal=portal, items=items,
                              dry_run=dry_run, run_once=run_once))

    async def portal_items(self, rules: PortalRules, prefs: CandidatePreferences,
                           profile: tuple[dict[str, Any], list[tuple[str, str]]], portal: PortalReport,
                           *, dry_run: bool, run_once: bool) -> AsyncGenerator[WorkItem, None]:
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
            seen.add(record.external_job_id)
            self.inspected_only.discard((platform, record.external_job_id))
            portal.requeued += 1
            yield WorkItem(self.backlog_listing(record), consume_id=record.id, via="requeue")
        # Phase 5: yesterday's quota-hit jobs whose retry is due run before new discoveries.
        if not dry_run:
            for record in await self.store.due_retries(platform, self.clock(), limit=DISCOVERY_LIMIT):
                seen.add(record.external_job_id)
                try:
                    record = await self.store.transition(record, S.SCORED, "quota_retry_due",
                                                         payload={"retry_after": record.retry_after})
                except InvalidTransition:
                    continue
                portal.retried += 1
                self.inspected_only.discard((platform, record.external_job_id))
                yield WorkItem(self.backlog_listing(record), via="backlog")
        portal.query = self.next_query(platform, prefs)
        self.note_discovery(platform)  # this search-page load counts as the portal's fresh sweep
        listings = await self.service.discover_listings(platform, portal.query, DISCOVERY_LIMIT, rules)
        portal.discovered = len(listings)
        backlog = await self.store.list_by_state(platform, BACKLOG_STATES, limit=DISCOVERY_LIMIT)
        # Phase 6A: never-processed DISCOVERED rows (job-alert emails, interrupted cycles), bounded.
        backlog += [r for r in await self.store.list_by_state(platform, (S.DISCOVERED,), limit=ALERT_BACKLOG_PER_CYCLE)
                    if r.job_url]
        candidates: list[WorkItem] = []
        for item in [*(self.backlog_listing(r) for r in backlog if r.job_url), *listings]:
            if item.external_job_id not in seen:
                seen.add(item.external_job_id)
                candidates.append(WorkItem(item, recycle=True))
        for work in candidates:
            yield work

    async def drive(self, turn: Turn) -> None:
        """Run a turn's jobs until done, stopped, interrupted or parked on a cooldown."""
        rules, portal = turn.rules, turn.portal
        platform = rules.platform
        parked = False
        try:
            while True:
                if not await self.should_continue(run_once=turn.run_once):
                    raise Interrupted
                item, turn.pushback = turn.pushback, None
                if item is None:
                    try:
                        item = await turn.items.__anext__()
                    except StopAsyncIteration:
                        return
                stop: str | None = None
                try:
                    stop = await self.handle_listing(item.listing, rules, turn.prefs, turn.profile, portal,
                                                     dry_run=turn.dry_run, run_once=turn.run_once, via=item.via)
                finally:
                    if item.consume_id is not None and stop != COOLDOWN:
                        await self.store.mark_hitl_consumed(item.consume_id)
                if stop == COOLDOWN:
                    turn.pushback, parked = item, True
                    portal.deferred += 1
                    self.deferred[platform] = turn
                    return
                if stop:
                    portal.stopped_reason = stop
                    return
                if item.recycle:
                    await self.service.manager.maybe_recycle_between_jobs(RECYCLE_AFTER_SEC)
                if self.circuit_blocked_until(platform, self.clock()) is not None:
                    portal.stopped_reason = "circuit_open"
                    return
                await self.drain_priority(run_once=turn.run_once)  # P0/P1 elsewhere jump the queue
        finally:
            if not parked:
                await turn.items.aclose()

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
        if status != "OK":
            logger.warning("session %s %s reason=%s details=%s screenshot=%s", platform, status, session.get("reason"),
                           session.get("details"), session.get("screenshot"))
        if status == "OK":
            self.session_ok_at[platform] = self.clock()
            await self.store.cancel_open_hitl(platform, "AUTH")
            return True
        self.session_ok_at.pop(platform, None)
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
                        self.session_ok_at[platform] = self.clock()
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
                             *, dry_run: bool, run_once: bool, via: str | None = None) -> str | None:
        """Process one job. Returns a reason to stop this portal, or None to continue.

        Phase 9B: COOLDOWN means "this portal may not click Apply yet" - the caller keeps the job."""
        platform, key = rules.platform, (rules.platform, listing.external_job_id)
        if key in self.inspected_only or key in self.attempted:
            return None  # Phase 9B: a job opened this cycle (e.g. errored) is not retried until the next
        existing = await self.store.get(platform, listing.external_job_id)
        if existing is not None and existing.state not in APPLY_ELIGIBLE:
            return None  # FILTERED_OUT, WAITING_FOR_USER, APPLYING, APPLIED, SUBMISSION_UNKNOWN
        _, verdict = await self.service.prefilter(listing, rules, prefs, record_filters=True, via=via,
                                                  now=self.clock())
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
        if live_apply and self.cooldown_until(platform, self.clock()) is not None:
            return COOLDOWN
        if portal.inspected and not await self.sleep(self.rng.uniform(*self.inspection_pause_sec),
                                                     run_once=run_once, wakeable=False):
            raise Interrupted
        portal.inspected += 1
        self.attempted.add(key)
        try:
            # auto_apply_enabled=false: inspect + score only (stops before the Apply click).
            outcome = await self.service.process_job(listing, dry_run=not live_apply, rules=rules,
                                                     profile=profile, record_filters=True, now=self.clock())
        except PortalWallActive:
            # A feed portal hit its login/challenge wall this cycle: stop it, jobs stay in the backlog.
            portal.outcomes.append({"external_job_id": listing.external_job_id, "stopped": "portal_wall"})
            await self.observe(platform, OutcomeCode.CAPTCHA_WALL, "portal_wall")
            return "portal_wall"
        except Exception as exc:  # noqa: BLE001 - isolate one job; post-click errors are already SUBMISSION_UNKNOWN
            portal.errors += 1
            portal.consecutive_errors += 1
            portal.outcomes.append({"external_job_id": listing.external_job_id,
                                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            logger.warning("job %s failed: %s", listing.external_job_id, type(exc).__name__)
            await self.observe(platform, OutcomeCode.INFRA_ERROR, f"job_error:{type(exc).__name__}")
            if portal.consecutive_errors >= MAX_CONSECUTIVE_JOB_ERRORS:
                return "consecutive_errors"  # likely a portal-wide outage: let the others run
            return None
        portal.consecutive_errors = 0
        await self.observe_outcome(platform, outcome)
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
            # Phase 9B: human-like jitter between live applications as a per-portal cooldown (plus a
            # global minimum gap) instead of a blocking sleep: other portals' work runs meanwhile.
            self.start_cooldown(rules)
        return None

    def next_query(self, platform: str, prefs: CandidatePreferences) -> str:
        queries = list(prefs.target_roles) or [DEFAULT_QUERY]
        index = self.query_index.get(platform, 0)
        self.query_index[platform] = index + 1
        return queries[index % len(queries)]

    @staticmethod
    def backlog_listing(record: Any) -> JobListing:
        # Phase 9: carry the stored posting time so backlog/priority rows keep a known age.
        posted_at = getattr(record, "posted_at", None)
        age = None
        if posted_at is not None:
            from datetime import UTC, datetime

            moment = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC)
            age = max((datetime.now(UTC) - moment).days, 0)
        return JobListing(platform=record.platform, external_job_id=record.external_job_id,
                          url=record.job_url or "", title=record.role_title, company=record.company_name,
                          posted_text=posted_at.isoformat() if posted_at is not None else None,
                          posted_age_days=age, posted_at=posted_at)
