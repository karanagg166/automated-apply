"""MemoryStore discovery upsert and early-bird priority queue (mixin; mirrors DiscoveryRepo SQL)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.priority import P0_DECAY_AFTER, P1_DECAY_AFTER, queue_key
from backend.app.browser_v2.rules import dedup_key
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.memory_base import MemoryBase
from backend.app.browser_v2.store.phase9_records import (
    PRIORITY_MUTABLE_STATES,
    PRIORITY_REASON_CHARS,
    DiscoveryMeta,
    DiscoveryResult,
    check_priority,
    precision_rank,
)
from backend.app.browser_v2.store.records import ApplicationRecord, _now

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def queue_sort_key(record: ApplicationRecord) -> tuple[int, float, float]:
    """Same order as Postgres: priority, COALESCE(posted_at, created_at) DESC, updated_at."""
    tier, newest = queue_key(record.priority, record.posted_at, record.created_at or _EPOCH)
    return tier, newest, (record.updated_at or _EPOCH).timestamp()


def _queued(record: ApplicationRecord) -> bool:
    return record.state.value in PRIORITY_MUTABLE_STATES


class MemoryPriorityMixin(MemoryBase):
    async def upsert_discovered(self, listing: JobListing, meta: DiscoveryMeta | None = None) -> ApplicationRecord:
        return (await self.upsert_discovered_meta(listing, meta)).record

    async def upsert_discovered_meta(self, listing: JobListing, meta: DiscoveryMeta | None) -> DiscoveryResult:
        meta = meta or DiscoveryMeta()
        key = (listing.platform, listing.external_job_id)
        if key not in self.records:
            self.records[key] = ApplicationRecord(
                id=f"mem-{len(self.records) + 1}", platform=listing.platform,
                external_job_id=listing.external_job_id, state=ApplicationState.DISCOVERED, version=1,
                company_name=listing.company, role_title=listing.title, job_url=listing.url,
                dedup_key=dedup_key(listing.company, listing.title), created_at=_now(),
                updated_at=_now(), priority=meta.priority if meta.priority is not None else 2,
                priority_reason=meta.priority_reason, posted_at=meta.posted_at,
                posted_precision=meta.posted_precision, discovered_via=meta.discovered_via)
            return DiscoveryResult(replace(self.records[key]), inserted=True, promoted=False)
        current = self.records[key]
        current.company_name = current.company_name or listing.company
        current.role_title = current.role_title or listing.title
        current.job_url = current.job_url or listing.url
        current.dedup_key = current.dedup_key or dedup_key(listing.company, listing.title)
        promoted = _queued(current) and meta.priority is not None and meta.priority < current.priority
        if promoted and meta.priority is not None:
            current.priority, current.priority_reason = meta.priority, meta.priority_reason
        if meta.posted_at is not None and (current.posted_at is None or precision_rank(meta.posted_precision)
                                           < precision_rank(current.posted_precision)):
            current.posted_at, current.posted_precision = meta.posted_at, meta.posted_precision
        current.discovered_via = current.discovered_via or meta.discovered_via
        return DiscoveryResult(replace(current), inserted=False, promoted=promoted)

    async def priority_candidates(self, now: datetime, *, max_priority: int = 1,
                                  platforms: Collection[str] | None = None,
                                  limit: int = 10) -> list[ApplicationRecord]:
        open_ids = {h.get("application_id") for h in self.hitl if h["status"] == "OPEN"}
        rows = [replace(r) for r in self.records.values()
                if r.priority <= max_priority and (platforms is None or r.platform in platforms)
                and (r.state == ApplicationState.SCORED
                     or (r.state == ApplicationState.DISCOVERED and r.job_url is not None))
                and (r.retry_after is None or r.retry_after <= now) and r.id not in open_ids]
        rows.sort(key=queue_sort_key)
        return rows[:limit]

    async def set_priority(self, application_id: str, priority: int, reason: str | None) -> bool:
        check_priority(priority)
        for record in self.records.values():
            if record.id == application_id:
                record.priority = priority
                record.priority_reason = reason[:PRIORITY_REASON_CHARS] if reason else None
                return True
        return False

    async def decay_priorities(self, now: datetime) -> int:
        p0_cutoff = now - P0_DECAY_AFTER
        p1_cutoff = now - (P0_DECAY_AFTER + P1_DECAY_AFTER)
        changed = 0
        for record in self.records.values():
            if not _queued(record) or record.created_at is None:
                continue
            if record.priority == 0 and record.created_at < p0_cutoff:
                record.priority = 1 if record.created_at >= p1_cutoff else 2
                record.priority_reason, changed = "decayed_from_p0", changed + 1
            elif record.priority == 1 and record.created_at < p1_cutoff:
                record.priority, record.priority_reason, changed = 2, "decayed_from_p1", changed + 1
        return changed
