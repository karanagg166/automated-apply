"""PostgresStore discovery upsert and early-bird priority queue (mixin over PostgresBase, followup 005)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.priority import P0_DECAY_AFTER, P1_DECAY_AFTER
from backend.app.browser_v2.rules import dedup_key
from backend.app.browser_v2.store.base import PostgresBase, _record, _uuid
from backend.app.browser_v2.store.phase9_records import (
    PRIORITY_REASON_CHARS,
    DiscoveryMeta,
    DiscoveryResult,
    check_priority,
)
from backend.app.browser_v2.store.records import ApplicationRecord

# Tier may only move for queued rows; in-flight / terminal / parked rows keep theirs.
_PROMOTE = ("(a.state IN ('DISCOVERED','SCORED') AND $7::smallint IS NOT NULL "
            "AND $7::smallint < a.priority)")
_RANK = "array_position(ARRAY['hour','day','unknown']::text[], {})"
_BETTER_POSTED = ("($9::timestamptz IS NOT NULL AND (a.posted_at IS NULL OR "
                  + _RANK.format("$10::text") + " < " + _RANK.format("COALESCE(a.posted_precision, 'unknown')")
                  + "))")
QUEUE_ORDER = "priority, COALESCE(posted_at, created_at) DESC, updated_at"


def upsert_sql(columns: str) -> str:
    """One statement: insert or fill-in, reporting inserted vs existing and the tier before the write.

    The DO UPDATE only fires when something would change (same as before Phase 9); otherwise the
    unchanged row is returned by the second UNION branch from the statement snapshot."""
    return f"""
WITH old AS (
    SELECT priority FROM public.applications WHERE platform=$1 AND external_job_id=$2),
up AS (
    INSERT INTO public.applications AS a
        (platform, external_job_id, company_name, role_title, job_url, dedup_key, state,
         priority, priority_reason, posted_at, posted_precision, discovered_via)
    VALUES ($1, $2, $3, $4, $5, $6, 'DISCOVERED', COALESCE($7::smallint, 2), $8::text,
            $9::timestamptz, $10::text, $11::text)
    ON CONFLICT (platform, external_job_id) DO UPDATE SET
        company_name=COALESCE(a.company_name, EXCLUDED.company_name),
        role_title=COALESCE(a.role_title, EXCLUDED.role_title),
        job_url=COALESCE(a.job_url, EXCLUDED.job_url),
        dedup_key=COALESCE(a.dedup_key, EXCLUDED.dedup_key),
        priority=CASE WHEN {_PROMOTE} THEN $7::smallint ELSE a.priority END,
        priority_reason=CASE WHEN {_PROMOTE} THEN $8::text ELSE a.priority_reason END,
        posted_at=CASE WHEN {_BETTER_POSTED} THEN $9::timestamptz ELSE a.posted_at END,
        posted_precision=CASE WHEN {_BETTER_POSTED} THEN $10::text ELSE a.posted_precision END,
        discovered_via=COALESCE(a.discovered_via, $11::text)
    WHERE a.dedup_key IS NULL OR a.company_name IS NULL OR a.role_title IS NULL OR a.job_url IS NULL
       OR {_PROMOTE} OR {_BETTER_POSTED} OR (a.discovered_via IS NULL AND $11::text IS NOT NULL)
    RETURNING {columns}, (xmax = 0) AS inserted)
SELECT {columns}, inserted, (SELECT priority FROM old) AS old_priority FROM up
UNION ALL
SELECT {columns}, false AS inserted, priority AS old_priority FROM public.applications
 WHERE platform=$1 AND external_job_id=$2 AND NOT EXISTS (SELECT 1 FROM up)"""


class DiscoveryRepo(PostgresBase):
    async def upsert_discovered(self, listing: JobListing, meta: DiscoveryMeta | None = None) -> ApplicationRecord:
        # Fill missing company/title/url/dedup_key on re-discovery; never touch state.
        return (await self.upsert_discovered_meta(listing, meta)).record

    async def upsert_discovered_meta(self, listing: JobListing, meta: DiscoveryMeta | None) -> DiscoveryResult:
        meta = meta or DiscoveryMeta()
        row = await self.connection.fetchrow(
            upsert_sql(self.COLUMNS),
            listing.platform, listing.external_job_id, listing.company, listing.title, listing.url,
            dedup_key(listing.company, listing.title), meta.priority, meta.priority_reason, meta.posted_at,
            meta.posted_precision, meta.discovered_via)
        if row is None:  # lost an insert race to another connection: the row exists now
            record = await self._fetch_listing(listing)
            return DiscoveryResult(record, inserted=False, promoted=False)
        record = _record(row)
        inserted = bool(row["inserted"])
        old = row["old_priority"]
        promoted = not inserted and old is not None and record.priority < int(old)
        return DiscoveryResult(record, inserted=inserted, promoted=promoted)

    async def _fetch_listing(self, listing: JobListing) -> ApplicationRecord:
        row = await self.connection.fetchrow(
            f"SELECT {self.COLUMNS} FROM public.applications WHERE platform=$1 AND external_job_id=$2",
            listing.platform, listing.external_job_id)
        assert row is not None
        return _record(row)

    async def priority_candidates(self, now: datetime, *, max_priority: int = 1,
                                  platforms: Collection[str] | None = None,
                                  limit: int = 10) -> list[ApplicationRecord]:
        """Urgent queued work across portals: SCORED rows and DISCOVERED rows with a job URL,
        not retry-blocked and without an OPEN HITL request, tier first then newest posting."""
        rows = await self.connection.fetch(
            f"""SELECT {self.COLUMNS} FROM public.applications a
                WHERE a.priority <= $2 AND ($3::text[] IS NULL OR a.platform = ANY($3::text[]))
                  AND (a.state = 'SCORED' OR (a.state = 'DISCOVERED' AND a.job_url IS NOT NULL))
                  AND (a.retry_after IS NULL OR a.retry_after <= $1)
                  AND NOT EXISTS (SELECT 1 FROM public.hitl_requests h
                                  WHERE h.application_id = a.id AND h.status = 'OPEN')
                ORDER BY {QUEUE_ORDER} LIMIT $4""",
            now, max_priority, sorted(platforms) if platforms is not None else None, limit)
        return [_record(r) for r in rows]

    async def set_priority(self, application_id: str, priority: int, reason: str | None) -> bool:
        """Owner/worker re-tier. No state, version or updated_at change (in-flight transitions
        keep their optimistic version)."""
        check_priority(priority)
        if _uuid(application_id) is None:
            return False
        result = await self.connection.execute(
            "UPDATE public.applications SET priority=$2, priority_reason=$3 WHERE id=$1::uuid",
            application_id, priority, reason[:PRIORITY_REASON_CHARS] if reason else None)
        return str(result).rsplit(" ", 1)[-1] not in ("", "0")

    async def decay_priorities(self, now: datetime) -> int:
        """Queued P0 older than 2 h -> P1; P1 older than 26 h -> P2 (by discovery time)."""
        p0_cutoff = now - P0_DECAY_AFTER
        p1_cutoff = now - (P0_DECAY_AFTER + P1_DECAY_AFTER)
        result = await self.connection.execute(
            """UPDATE public.applications SET
                   priority = CASE WHEN priority = 0 AND created_at >= $2 THEN 1 ELSE 2 END,
                   priority_reason = CASE WHEN priority = 0 THEN 'decayed_from_p0' ELSE 'decayed_from_p1' END
               WHERE state IN ('DISCOVERED','SCORED')
                 AND ((priority = 0 AND created_at < $1) OR (priority = 1 AND created_at < $2))""",
            p0_cutoff, p1_cutoff)
        return int(str(result).rsplit(" ", 1)[-1] or 0)
