"""PostgresStore owner-requested queue writes with the never-replay fence enforced in the store."""

from __future__ import annotations

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.store.agent_records import FENCED_STATES, FencedRowError
from backend.app.browser_v2.store.base import _uuid
from backend.app.browser_v2.store.discovery_repo import DiscoveryRepo
from backend.app.browser_v2.store.phase9_records import (
    PRIORITY_REASON_CHARS,
    DiscoveryMeta,
    DiscoveryResult,
    check_priority,
)


class OwnerQueueRepo(DiscoveryRepo):
    async def enqueue_owner_job(self, listing: JobListing, meta: DiscoveryMeta) -> DiscoveryResult:
        """Upsert an owner-pasted job; refuses (FencedRowError) when the row is APPLIED/SUBMISSION_UNKNOWN."""
        state = await self.connection.fetchval(
            "SELECT state FROM public.applications WHERE platform = $1 AND external_job_id = $2",
            listing.platform, listing.external_job_id)
        if state in FENCED_STATES:
            raise FencedRowError(str(state))
        return await self.upsert_discovered_meta(listing, meta)

    async def set_owner_priority(self, application_id: str, priority: int, reason: str | None) -> bool:
        """Re-tier one row unless it is fenced (FencedRowError). False when the row does not exist."""
        check_priority(priority)
        if _uuid(application_id) is None:
            return False
        updated = await self.connection.fetchval(
            """UPDATE public.applications SET priority = $2, priority_reason = $3
               WHERE id = $1::uuid AND state <> ALL($4::text[]) RETURNING id""",
            application_id, priority, reason[:PRIORITY_REASON_CHARS] if reason else None, list(FENCED_STATES))
        if updated is not None:
            return True
        state = await self.connection.fetchval("SELECT state FROM public.applications WHERE id = $1::uuid",
                                               application_id)
        if state in FENCED_STATES:
            raise FencedRowError(str(state))
        return False
