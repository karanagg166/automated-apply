"""BrowserService ATS handoff and verified SUBMISSION_UNKNOWN reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.priority import better
from backend.app.browser_v2.service.gates import GatesMixin
from backend.app.browser_v2.service.helpers import S
from backend.app.browser_v2.store import ApplicationRecord, DiscoveryMeta
from backend.app.browser_v2.store.phase9_records import PRIORITY_MUTABLE_STATES


class HandoffMixin(GatesMixin):
    # --- Phase 8b: verified reconciliation of SUBMISSION_UNKNOWN ---------------------------------
    async def reconcile_submissions(self, platform: str, *, limit: int = 20,
                                    max_age: timedelta = timedelta(days=14)) -> list[dict[str, Any]]:
        """SUBMISSION_UNKNOWN rows (never migrated history) -> APPLIED only when the portal's own
        application history shows exactly one matching "Application sent". Never clicks anything."""
        from backend.app.browser_v2.state import RECONCILE_REASON

        adapter: Any = self.adapters.get(platform)
        if adapter is None or not hasattr(adapter, "history_rows"):
            return []
        cutoff = datetime.now(UTC) - max_age
        pending = [r for r in await self.store.list_by_state(platform, (S.SUBMISSION_UNKNOWN,), limit=limit)
                   if not (r.reason or "").startswith("migrated_") and r.role_title and r.company_name
                   and (r.updated_at is None or r.updated_at >= cutoff)]
        if not pending:
            return []
        async with self.manager.job() as page:
            rows = await adapter.history_rows(page)
        results = []
        for record in pending:
            match = adapter.history_match(rows, record.role_title, record.company_name)
            if match is None:
                results.append({"external_job_id": record.external_job_id, "state": record.state.value,
                                "verified": False})
                continue
            receipt = {"source": "application_history", "status": match.get("status"),
                       "verified_at": datetime.now(UTC).isoformat(), "previous_reason": record.reason}
            moved = await self.store.transition(record, S.APPLIED, RECONCILE_REASON, receipt=receipt)
            await self.publish("job.applied", {"platform": platform, "external_job_id": record.external_job_id,
                                               "company": record.company_name, "title": record.role_title,
                                               "url": record.job_url, "priority": record.priority,
                                               "reconciled": True})
            results.append({"external_job_id": record.external_job_id, "state": moved.state.value,
                            "verified": True, "status": match.get("status")})
        return results

    # --- Phase 8: smart external ATS handoff --------------------------------------------------
    def handoff_target(self, platform: str, detail: Any) -> Any:
        """Supported Greenhouse/Lever posting behind another portal's external apply link."""
        from backend.app.browser_v2.adapters.common import (
            SUPPORTED_ATS,
            ats_handoff_target,
        )

        if platform in SUPPORTED_ATS or detail.apply_mode != "external":
            return None
        target = ats_handoff_target(detail.apply_url)
        return target if target is not None and target.platform in self.adapters else None

    async def hand_off(self, record: ApplicationRecord, detail: Any, target: Any, *,
                       record_filters: bool) -> dict[str, Any]:
        """Enqueue the posting for the greenhouse/lever adapter (DISCOVERED, deduped by the ATS job
        id) and close the source row as FILTERED_OUT `ats_handoff:<ats>:<id>` - never applied twice."""
        reason = f"ats_handoff:{target.platform}:{target.external_job_id}"
        result: dict[str, Any] = {"state": S.FILTERED_OUT.value, "reason": reason, "handoff": {
            "platform": target.platform, "external_job_id": target.external_job_id, "url": target.url,
            "board": target.board, "board_guessed": target.board_guessed}}
        if not record_filters:
            return result | {"handoff_recorded": False}
        existing = await self.store.get(target.platform, target.external_job_id)
        # Phase 9B: the ATS row inherits the source row's early-bird tier (never demoted).
        tier = better(record.priority, existing.priority if existing is not None else None)
        if existing is None:
            listing = detail.listing
            existing = (await self.store.upsert_discovered_meta(JobListing(
                platform=target.platform, external_job_id=target.external_job_id, url=target.url,
                title=listing.title, company=listing.company, posted_text=listing.posted_text,
                posted_age_days=detail.posted_age_days, age_is_lower_bound=listing.age_is_lower_bound,
                applicants=detail.applicants), DiscoveryMeta(
                    priority=tier, priority_reason=f"ats_handoff_from:{record.platform}"[:200],
                    posted_at=record.posted_at, posted_precision=record.posted_precision,
                    discovered_via=f"ats_handoff:{record.platform}"))).record
        elif tier < existing.priority and existing.state.value in PRIORITY_MUTABLE_STATES:
            await self.store.set_priority(existing.id, tier, f"ats_handoff_from:{record.platform}")
        result["handoff"]["state"] = existing.state.value
        await self.filter_out(record, reason, record_filters=True)
        await self.publish("job.ats_handoff", {"from": record.platform, "to": target.platform,
                                               "external_job_id": target.external_job_id})
        return result | {"handoff_recorded": True}
