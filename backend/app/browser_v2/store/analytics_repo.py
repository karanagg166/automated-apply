"""PostgresStore analytics: the agent funnel (applications + read-only recruiter-reply events) and the
dashboard's per-portal application summary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from backend.app.browser_v2.store.agent_records import REPLY_KINDS, empty_funnel
from backend.app.browser_v2.store.base import PostgresBase

FUNNEL_SQL = """
SELECT platform,
       count(*) FILTER (WHERE created_at >= $1) AS discovered,
       count(*) FILTER (WHERE state = 'FILTERED_OUT' AND updated_at >= $1) AS filtered,
       count(*) FILTER (WHERE state = 'APPLIED' AND applied_at >= $1) AS applied,
       count(*) FILTER (WHERE state = 'FAILED' AND updated_at >= $1) AS failed,
       count(*) FILTER (WHERE state = 'WAITING_FOR_USER' AND updated_at >= $1) AS waiting,
       count(*) FILTER (WHERE state IN ('QUOTA_HIT_PENDING', 'DRAFTED_AND_QUEUED') AND updated_at >= $1) AS quota,
       count(*) FILTER (WHERE state = 'SUBMISSION_UNKNOWN' AND updated_at >= $1) AS submission_unknown
FROM public.applications
WHERE (created_at >= $1 OR updated_at >= $1 OR applied_at >= $1) AND ($2::text IS NULL OR platform = $2)
GROUP BY platform"""
REPLIES_SQL = """
SELECT COALESCE(platform, 'unknown') AS platform, count(*) AS replies FROM public.mail_events
WHERE kind = ANY($3::text[]) AND created_at >= $1 AND ($2::text IS NULL OR platform = $2)
GROUP BY 1"""
SUMMARY_STATES_SQL = "SELECT platform, state, count(*) AS n FROM public.applications GROUP BY platform, state"
SUMMARY_DAILY_SQL = """
SELECT platform, (applied_at AT TIME ZONE $2)::date AS day, count(*) AS n FROM public.applications
WHERE state = 'APPLIED' AND applied_at >= $1
GROUP BY 1, 2"""

# (per-platform {state: count}, [(platform, local applied date, count)])
SummaryCounts = tuple[dict[str, dict[str, int]], list[tuple[str, date, int]]]


def funnel_since(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=max(1, min(int(days), 90)))


class AnalyticsRepo(PostgresBase):
    async def funnel(self, days: int = 7, platform: str | None = None, *,
                     now: datetime | None = None) -> dict[str, dict[str, int]]:
        """Per-platform counts over the last `days` (1..90): discovered, filtered, applied, failed,
        waiting, quota, submission_unknown (+ recruiter_replies from mail_events when present)."""
        since = funnel_since(days, now)
        out: dict[str, dict[str, int]] = {}
        for row in await self.connection.fetch(FUNNEL_SQL, since, platform):
            data = dict(row)
            name = data.pop("platform")
            out[name] = empty_funnel() | {k: int(v or 0) for k, v in data.items()}
        if await self.connection.fetchval("SELECT to_regclass('public.mail_events') IS NOT NULL"):
            for row in await self.connection.fetch(REPLIES_SQL, since, platform, list(REPLY_KINDS)):
                bucket = out.setdefault(row["platform"], empty_funnel())
                bucket["recruiter_replies"] = int(row["replies"] or 0)
        return out

    async def application_summary(self, since: datetime, tz: str) -> SummaryCounts:
        """All-time counts per platform and state, plus APPLIED rows per platform per local day
        (`applied_at` converted to the IANA zone `tz`) for applications applied at/after `since`."""
        states: dict[str, dict[str, int]] = {}
        for row in await self.connection.fetch(SUMMARY_STATES_SQL):
            states.setdefault(row["platform"], {})[row["state"]] = int(row["n"])
        daily = [(row["platform"], row["day"], int(row["n"]))
                 for row in await self.connection.fetch(SUMMARY_DAILY_SQL, since, tz)]
        return states, daily
