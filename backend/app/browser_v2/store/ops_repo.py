"""PostgresStore ops queries (Milestone 2): command-center telemetry and the SSE delta feed.

Read-only and bounded. The delta feed is polled by the API's EventHub over a pooled connection
(one short query batch every few seconds), never a dedicated LISTEN connection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.browser_v2.store.base import PostgresBase

ACTIVE_JOB_SQL = """
SELECT a.id, a.platform, a.company_name, a.role_title, a.updated_at,
       (SELECT e.event_type FROM public.application_state_events e
         WHERE e.application_id = a.id ORDER BY e.created_at DESC LIMIT 1) AS step
FROM public.applications a WHERE a.state = 'APPLYING' ORDER BY a.updated_at DESC LIMIT 1"""
LAGS_SQL = """
SELECT (receipt->'timing'->>'first_mover_lag_seconds')::numeric AS lag FROM public.applications
WHERE state = 'APPLIED' AND applied_at >= $1
  AND jsonb_typeof(receipt->'timing'->'first_mover_lag_seconds') = 'number'
ORDER BY applied_at DESC LIMIT 500"""
RECEIPTS_SQL = """
SELECT count(*) FILTER (WHERE state = 'APPLIED' AND applied_at >= $1
                          AND COALESCE(receipt->>'email_verified', 'false') = 'true') AS verified_today,
       count(*) FILTER (WHERE state = 'SUBMISSION_UNKNOWN' AND updated_at < $2
                          AND COALESCE(receipt->>'email_verified', 'false') <> 'true') AS needs_reconciliation
FROM public.applications WHERE state IN ('APPLIED', 'SUBMISSION_UNKNOWN')"""
SOURCES_SQL = """
SELECT answer->>'source' AS source, count(*) AS n
FROM public.application_state_events e, jsonb_array_elements(
       CASE WHEN jsonb_typeof(e.payload->'answers') = 'array' THEN e.payload->'answers' ELSE '[]'::jsonb END
     ) AS answer
WHERE e.created_at >= $1 GROUP BY 1"""
WATCHERS_SQL = """
SELECT count(*) FROM public.watcher_state
WHERE last_poll_at >= $1 AND (open_until IS NULL OR open_until <= $2)"""
FEED_EVENTS_SQL = """
SELECT e.id, e.application_id, e.from_state, e.to_state, e.event_type, e.created_at,
       a.platform, a.company_name, a.role_title, a.priority
FROM public.application_state_events e JOIN public.applications a ON a.id = e.application_id
WHERE e.created_at > $1 ORDER BY e.created_at, e.id LIMIT $2"""
FEED_HITL_SQL = """
SELECT h.id, h.application_id, h.platform, h.kind, h.status, h.prompt_text, h.created_at, h.resolved_at,
       h.resolved_via
FROM public.hitl_requests h WHERE h.created_at > $1 OR h.resolved_at > $1
ORDER BY COALESCE(h.resolved_at, h.created_at) LIMIT $2"""
FEED_WORKER_SQL = """
SELECT desired_state, dry_run, observed_state, current_platform, heartbeat_at, last_error, revision
FROM public.worker_control WHERE singleton_key = 'primary'"""
FEED_BREAKERS_SQL = """
SELECT platform, enabled, auth_status, circuit_level, circuit_open_until, circuit_reason
FROM public.portal_rules ORDER BY platform"""


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


class OpsRepo(PostgresBase):
    async def ops_active_job(self) -> dict[str, Any] | None:
        row = await self.connection.fetchrow(ACTIVE_JOB_SQL)
        if row is None:
            return None
        return {"application_id": str(row["id"]), "platform": row["platform"], "company": row["company_name"],
                "title": row["role_title"], "step": row["step"] or "apply_started", "started_at": row["updated_at"]}

    async def ops_first_mover_lags(self, since: datetime) -> list[float]:
        return [float(row["lag"]) for row in await self.connection.fetch(LAGS_SQL, since) if row["lag"] is not None]

    async def ops_receipt_counts(self, since: datetime, stale_before: datetime) -> dict[str, int]:
        row = await self.connection.fetchrow(RECEIPTS_SQL, since, stale_before)
        return {"verified_today": int(row["verified_today"] or 0) if row else 0,
                "needs_reconciliation": int(row["needs_reconciliation"] or 0) if row else 0}

    async def ops_answer_sources(self, since: datetime) -> dict[str, int]:
        return {str(row["source"]): int(row["n"]) for row in await self.connection.fetch(SOURCES_SQL, since)
                if row["source"]}

    async def ops_active_watchers(self, since: datetime, now: datetime) -> int:
        if not await self.connection.fetchval("SELECT to_regclass('public.watcher_state') IS NOT NULL"):
            return 0
        return int(await self.connection.fetchval(WATCHERS_SQL, since, now) or 0)

    async def ops_pushes_since(self, since: datetime) -> int:
        """Telegram pushes recorded in the notification ledger since `since` (followup 007)."""
        if not await self.connection.fetchval("SELECT to_regclass('public.telegram_notification_ledger') IS NOT NULL"):
            return 0
        return int(await self.connection.fetchval(
            "SELECT count(*) FROM public.telegram_notification_ledger WHERE last_sent_at >= $1", since) or 0)

    async def ops_event_feed(self, since: datetime, limit: int = 200) -> dict[str, Any]:
        """Deltas since `since` for the SSE hub: state events, HITL changes, worker row, breakers."""
        events = [{**{k: _iso(v) for k, v in dict(row).items()}, "id": str(row["id"]),
                   "application_id": str(row["application_id"])}
                  for row in await self.connection.fetch(FEED_EVENTS_SQL, since, limit)]
        hitl = [{**{k: _iso(v) for k, v in dict(row).items()}, "id": str(row["id"]),
                 "application_id": str(row["application_id"]) if row["application_id"] else None}
                for row in await self.connection.fetch(FEED_HITL_SQL, since, limit)]
        worker_row = await self.connection.fetchrow(FEED_WORKER_SQL)
        worker = {k: _iso(v) for k, v in dict(worker_row).items()} if worker_row is not None else None
        breakers = [{k: _iso(v) for k, v in dict(row).items()}
                    for row in await self.connection.fetch(FEED_BREAKERS_SQL)]
        return {"events": events, "hitl": hitl, "worker": worker, "breakers": breakers}
