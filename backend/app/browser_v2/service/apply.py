"""BrowserService apply path: inspect -> dedup -> filter -> reserve -> apply."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.quota import contact_hints
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    Decision,
    PortalRules,
    evaluate_pipeline,
    format_reason,
    is_title_mismatch_only,
)
from backend.app.browser_v2.service.handoff import HandoffMixin
from backend.app.browser_v2.service.helpers import S, apply_env_profile, plain
from backend.app.browser_v2.service.registry import job_id_from_url
from backend.app.browser_v2.state import ReplayRefused, guard_apply
from backend.app.browser_v2.submit_marker import (
    pre_submit_failure_reason,
    submit_scope,
    tracks_submit,
)

logger = logging.getLogger(__name__)
MAX_PRE_SUBMIT_ATTEMPTS = 3  # APPLYING reservations (attempts) before a hanging job stops being retried


class ApplyMixin(HandoffMixin):
    async def apply_to_job(self, platform: str, url: str, *, dry_run: bool = True) -> dict[str, Any]:
        """Filter, guard and apply to one job URL (CLI/MCP)."""
        self.adapter(platform)
        job_id = job_id_from_url(platform, url)
        if not job_id:
            raise ValueError("unrecognized_job_url")
        listing = JobListing(platform=platform, external_job_id=job_id, url=url)
        return await self.process_job(listing, dry_run=dry_run)

    async def process_job(self, listing: JobListing, *, dry_run: bool,
                          rules: PortalRules | None = None,
                          profile: tuple[dict[str, Any], list[tuple[str, str]]] | None = None,
                          record_filters: bool | None = None, park_reason: str | None = None,
                          now: datetime | None = None) -> dict[str, Any]:
        """Inspect -> dedup -> filter pipeline -> (dry-run stop | reserve APPLYING -> apply).

        Live mode reserves APPLYING before clicking; any exception after the
        reservation becomes SUBMISSION_UNKNOWN (never replayed).
        Phase 5: `park_reason` (daily quota already hit) inspects and filters only, then
        parks a passing job as QUOTA_HIT_PENDING for the Gmail-draft + next-day retry path.
        """
        platform, job_id = listing.platform, listing.external_job_id
        record_filters = (not dry_run) if record_filters is None else record_filters
        adapter = self.adapter(platform)
        existing = await self.store.get(platform, job_id)
        try:
            guard_apply(existing.state if existing else None)
        except ReplayRefused as exc:
            return {"external_job_id": job_id, "refused": str(exc)}
        rules = rules or await self.store.get_rules(platform)
        if not dry_run:
            blocked = await self.quota_block(platform, rules, now)
            if blocked:
                return {"external_job_id": job_id, "state": S.QUOTA_HIT_PENDING.value, "reason": blocked,
                        "quota_blocked": True}
        loaded_profile, reviewed = profile if profile is not None else await self.store.load_profile()
        facts = apply_env_profile(CandidateFacts.from_profile(loaded_profile, reviewed), self.env_profile)
        prefs = CandidatePreferences.from_profile(loaded_profile)
        if self.ai is not None:
            self.ai.bind_profile(loaded_profile)
        hitl_id = None
        # Owner answers resolved via Telegram/dashboard HITL (one-time answers included).
        hitl_answers = await self.store.hitl_answers(existing.id) if existing is not None else {}
        async with self.manager.job() as page:
            detail = await adapter.inspect_job(page, listing)
            record = await self.store.upsert_discovered(detail.listing)
            try:
                guard_apply(record.state)
            except ReplayRefused as exc:
                return {"external_job_id": job_id, "refused": str(exc)}
            summary: dict[str, Any] = {
                "external_job_id": job_id, "application_id": record.id, "title": detail.listing.title,
                "company": detail.listing.company, "posted_age_days": detail.posted_age_days,
                "applicants": plain(detail.applicants), "apply_mode": detail.apply_mode,
                "salary": detail.salary_text, "dry_run": dry_run}
            duplicate = None if detail.already_applied else await self.duplicate_of(record)
            if duplicate is not None:
                reason = f"duplicate_of: {duplicate.platform}:{duplicate.external_job_id} ({duplicate.state.value})"
                await self.filter_out(record, reason, record_filters=record_filters)
                return summary | {"filter": Decision.FILTERED.value, "state": S.FILTERED_OUT.value,
                                  "reason": reason}
            verdict = evaluate_pipeline(
                age_days=detail.posted_age_days, applicants=detail.applicants, rules=rules, prefs=prefs,
                title=detail.listing.title, company=detail.listing.company,
                description=detail.description, salary_text=detail.salary_text,
                work_mode=detail.work_mode, age_is_lower_bound=detail.listing.age_is_lower_bound,
                experience_text=detail.listing.experience_text)
            if is_title_mismatch_only(verdict) and self.gray_zone_possible(detail.listing.title, prefs):
                verdict = await self.gray_zone_verdict(
                    verdict, title=detail.listing.title, company=detail.listing.company,
                    description=detail.description, prefs=prefs,
                    passes_without_title=evaluate_pipeline(
                        age_days=detail.posted_age_days, applicants=detail.applicants, rules=rules,
                        prefs=replace(prefs, target_roles=()), title=detail.listing.title,
                        company=detail.listing.company, description=detail.description,
                        salary_text=detail.salary_text, work_mode=detail.work_mode,
                        age_is_lower_bound=detail.listing.age_is_lower_bound,
                        experience_text=detail.listing.experience_text))
            summary |= {"filter": verdict.decision.value, "filter_reasons": list(verdict.reasons)}
            if verdict.decision is not Decision.PASS and not detail.already_applied:
                reason = format_reason(verdict)
                await self.filter_out(record, reason, record_filters=record_filters)
                return summary | {"state": S.FILTERED_OUT.value, "reason": reason}
            handoff = self.handoff_target(platform, detail)
            if handoff is not None and not detail.already_applied:
                return summary | await self.hand_off(record, detail, handoff, record_filters=record_filters)
            hints = contact_hints(detail)
            if record_filters and record.state in {S.DISCOVERED, S.FAILED}:
                record = await self.store.transition(record, S.SCORED, "passed_filters",
                                                     payload={"reasons": list(verdict.reasons),
                                                              "contact_hints": hints})
            if detail.portal_limit:
                await self.store.record_portal_limit(platform)
                if record_filters and record.state == S.SCORED:
                    await self.store.transition(record, S.QUOTA_HIT_PENDING, "portal_daily_limit",
                                                payload={"limit_text": detail.portal_limit,
                                                         "contact_hints": hints})
                return summary | {"state": S.QUOTA_HIT_PENDING.value, "reason": "portal_daily_limit",
                                  "portal_limit": True}
            if park_reason is not None:
                if record_filters and record.state == S.SCORED:
                    await self.store.transition(record, S.QUOTA_HIT_PENDING, park_reason,
                                                payload={"contact_hints": hints})
                    return summary | {"state": S.QUOTA_HIT_PENDING.value, "reason": park_reason, "parked": True}
                return summary | {"state": record.state.value, "reason": "not_parked"}
            if dry_run:
                result = await adapter.apply_job(page, detail, facts, dry_run=True,
                                                 existing_state=record.state.value,
                                                 hitl_answers=hitl_answers)
                return summary | plain(result)
            record = await self.store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
            started_at = datetime.now(UTC)
            try:
                with submit_scope() as marker:
                    result = await adapter.apply_job(page, detail, facts, dry_run=False,
                                                     existing_state=S.DISCOVERED.value,
                                                     hitl_answers=hitl_answers)
            except BaseException as exc:  # incl. CancelledError (SIGTERM): never leave APPLYING behind
                if tracks_submit(adapter) and not marker.attempted:
                    # Milestone 2: the hang/crash happened BEFORE the submit click (nothing reached the
                    # employer): retryable FAILED_TIMEOUT that never burns the daily quota.
                    await self.reservation_failed(record, pre_submit_failure_reason(exc))
                else:
                    await self.reservation_unknown(record, "exception_after_reservation:" + type(exc).__name__)
                raise
            try:
                after_click = self.after_click_handoff(platform, detail, result)
                if after_click is not None:
                    return summary | await self.hand_off(record, *after_click, record_filters=True)
                receipt = result.receipt
                if result.state == S.APPLIED:
                    receipt = (receipt or {}) | first_mover_timing(record, started_at, datetime.now(UTC))
                record = await self.store.transition(
                    record, result.state, result.reason, receipt=receipt,
                    payload={"answers": list(result.answers), "clicked_apply": result.clicked_apply,
                             "screenshot": result.screenshot})
            except BaseException as exc:
                await self.reservation_unknown(record, "outcome_write_failed:" + type(exc).__name__)
                raise
            if result.reason.startswith("portal_daily_limit"):
                await self.store.record_portal_limit(platform)
            if result.state == S.APPLIED:
                timing = (record.receipt or {}).get("timing") or {}
                await self.publish("job.applied", {"platform": platform, "external_job_id": job_id,
                                                   "company": detail.listing.company, "title": detail.listing.title,
                                                   "url": detail.listing.url, "priority": record.priority,
                                                   "first_mover_lag_seconds": timing.get("first_mover_lag_seconds")})
            elif result.state == S.QUOTA_HIT_PENDING:
                await self.publish("job.quota_hit", {"platform": platform, "external_job_id": job_id,
                                                     "reason": result.reason})
            if result.question is not None:
                hitl_id = await self.store.create_hitl(
                    record, platform, result.question.kind, result.question.prompt,
                    plain(result.question) | {"clicked_apply": result.clicked_apply,
                                              "title": detail.listing.title,
                                              "company": detail.listing.company,
                                              "url": detail.listing.url})
                await self.publish("hitl.opened", {"platform": platform, "kind": result.question.kind,
                                                   "external_job_id": job_id})
        await self.manager.maybe_recycle_between_jobs()
        return summary | plain(result) | {"hitl_request_id": hitl_id}

    async def reservation_failed(self, record: Any, reason: str) -> None:
        """APPLYING -> FAILED for a failure proven to precede the submit click (retry-eligible).

        A job that keeps hanging before submit is parked as FILTERED_OUT after MAX_PRE_SUBMIT_ATTEMPTS
        (the owner can re-score it) instead of being re-opened on every rediscovery."""
        exhausted = int(getattr(record, "attempts", 0) or 0) >= MAX_PRE_SUBMIT_ATTEMPTS
        target, why = (S.FILTERED_OUT, "pre_submit_failures_exhausted") if exhausted else (S.FAILED, reason)
        try:
            await self.store.transition(record, target, why[:80], payload={"submit_attempted": False,
                                                                            "last_failure": reason[:80]})
        except Exception as exc:  # noqa: BLE001 - fall back to the never-replay fence
            logger.warning("could not mark %s FAILED (%s): %s", getattr(record, "id", "?"), reason,
                           type(exc).__name__)
            await self.reservation_unknown(record, reason)

    async def reservation_unknown(self, record: Any, reason: str) -> None:
        """Best effort APPLYING -> SUBMISSION_UNKNOWN (never-replay); the stale-APPLYING sweep
        (`WorkerLoop.recover_stale_applying`) catches whatever this cannot write."""
        try:
            await self.store.transition(record, S.SUBMISSION_UNKNOWN, reason[:80])
        except Exception as exc:  # noqa: BLE001 - the original exception is what the caller re-raises
            logger.warning("could not mark %s SUBMISSION_UNKNOWN (%s): %s", getattr(record, "id", "?"),
                           reason, type(exc).__name__)


def first_mover_timing(record: Any, started_at: datetime, submitted_at: datetime) -> dict[str, Any]:
    """Receipt `timing`: discovered (first seen) -> started -> submitted, and the first-mover lag
    measured from the real posting time when known, else from first discovery."""
    discovered = getattr(record, "created_at", None)
    posted = getattr(record, "posted_at", None)
    origin = posted or discovered
    timing: dict[str, Any] = {
        "discovered_at": discovered.isoformat() if discovered else None,
        "posted_at": posted.isoformat() if posted else None,
        "started_at": started_at.isoformat(), "submitted_at": submitted_at.isoformat(),
        "apply_seconds": round((submitted_at - started_at).total_seconds(), 1),
        "first_mover_lag_seconds": round((submitted_at - origin).total_seconds()) if origin else None,
        "lag_from": "posted_at" if posted else ("discovered_at" if discovered else None),
        "priority": getattr(record, "priority", None)}
    return {"timing": timing}
