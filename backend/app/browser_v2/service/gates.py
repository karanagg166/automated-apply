"""BrowserService gates: quota, cross-portal dedup, filtering and the search-card prefilter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    CandidatePreferences,
    Decision,
    FilterResult,
    PortalRules,
    evaluate_pipeline,
    format_reason,
    is_title_mismatch_only,
)
from backend.app.browser_v2.service.base import BrowserServiceBase
from backend.app.browser_v2.service.helpers import (
    DUPLICATE_BLOCKING,
    S,
    can_move,
    quota_counts,
)
from backend.app.browser_v2.service.scoring import score_listing
from backend.app.browser_v2.store import ApplicationRecord


class GatesMixin(BrowserServiceBase):
    async def quota_block(self, platform: str, rules: PortalRules | None = None,
                          now: datetime | None = None) -> str | None:
        rules = rules or await self.store.get_rules(platform)
        counts = await quota_counts(self.store, rules, now)
        if counts["daily_limit_hit"]:
            return "dashboard_daily_limit"
        if counts["portal_limit_hit_today"]:
            return "portal_daily_limit"
        if counts["hourly_limit_hit"]:
            return "dashboard_hourly_limit"
        return None

    async def duplicate_of(self, record: ApplicationRecord) -> ApplicationRecord | None:
        """Cross-portal dedup on normalized company::role (never apply to the same role twice)."""
        if not record.dedup_key:
            return None
        for other in await self.store.find_duplicates(record.dedup_key, platform=record.platform,
                                                      external_job_id=record.external_job_id):
            if other.state in DUPLICATE_BLOCKING:
                return other
        return None

    async def filter_out(self, record: ApplicationRecord, reason: str, *, record_filters: bool
                         ) -> ApplicationRecord:
        if record_filters and record.state != S.FILTERED_OUT and can_move(record, S.FILTERED_OUT):
            return await self.store.transition(record, S.FILTERED_OUT, reason)
        return record

    async def prefilter(self, listing: JobListing, rules: PortalRules, prefs: CandidatePreferences,
                        *, record_filters: bool, via: str | None = None, newly_seen: bool = False,
                        now: datetime | None = None) -> tuple[ApplicationRecord, FilterResult | None]:
        """Cheap search-card checks before opening the job page (no browser work).

        Phase 9B: the row is upserted with its early-bird tier (`score_listing`); `via` records the
        discovery path ("sweep:<platform>", "backlog", "watcher:<src>", default "discovery")."""
        verdict = evaluate_pipeline(
            age_days=listing.posted_age_days, applicants=listing.applicants or UNKNOWN_APPLICANTS,
            rules=rules, prefs=prefs, title=listing.title, company=listing.company,
            age_is_lower_bound=listing.age_is_lower_bound, require_description=False,
            experience_text=listing.experience_text)
        meta = score_listing(listing, prefs, now=now or datetime.now(UTC), newly_seen=newly_seen, via=via,
                             passed=verdict.decision is Decision.PASS)
        discovered = await self.store.upsert_discovered_meta(listing, meta)
        record = discovered.record
        duplicate = await self.duplicate_of(record)
        if duplicate is not None:
            reason = f"duplicate_of: {duplicate.platform}:{duplicate.external_job_id} ({duplicate.state.value})"
            return await self.filter_out(record, reason, record_filters=record_filters), FilterResult(
                Decision.FILTERED, (reason,))
        # Unknown age/applicants on a card are re-checked on the job page; only hard fails stop here.
        if is_title_mismatch_only(verdict) and self.gray_zone_possible(listing.title, prefs):
            # Ambiguous title: open the JD (all other card-level filters must still pass).
            verdict = evaluate_pipeline(
                age_days=listing.posted_age_days, applicants=listing.applicants or UNKNOWN_APPLICANTS,
                rules=rules, prefs=replace(prefs, target_roles=()), title=listing.title,
                company=listing.company, age_is_lower_bound=listing.age_is_lower_bound,
                require_description=False, experience_text=listing.experience_text)
        if verdict.decision is Decision.FILTERED:
            return await self.filter_out(record, format_reason(verdict),
                                         record_filters=record_filters), verdict
        if (discovered.inserted or discovered.promoted) and record.priority <= 1:
            await self.publish("job.priority_discovered", {
                "platform": record.platform, "external_job_id": record.external_job_id,
                "priority": record.priority, "reason": record.priority_reason, "via": meta.discovered_via,
                "company": record.company_name, "title": record.role_title, "url": record.job_url})
        return record, None
