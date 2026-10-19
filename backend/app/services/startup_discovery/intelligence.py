"""Fresh evidence determines size and hiring; absence of jobs is never a negative statement."""

from datetime import timedelta

from backend.app.models.discovery import now
from backend.app.services.startup_discovery.normalizer import utc


def company_size(observations, days=180):
    eligible = [
        o
        for o in observations
        if not o.attributes.get("historical")
        and utc(o.observed_at) >= now() - timedelta(days=days)
        and o.verification_status in {"source_reported", "human_confirmed"}
        and o.attributes.get("team_size_band", "unknown") != "unknown"
    ]
    confirmed = [o for o in eligible if o.verification_status == "human_confirmed"]
    eligible = confirmed or eligible
    # Keep the latest snapshot per source identity; compare independent concurrent claims.
    latest = {}
    for o in sorted(
        eligible, key=lambda o: (utc(o.observed_at), str(o.id)), reverse=True
    ):
        latest.setdefault((o.source, o.identity_key), o)
    candidates = list(latest.values())
    bands = {o.attributes["team_size_band"] for o in candidates}
    counts = {
        o.attributes["employee_count"]
        for o in candidates
        if o.attributes.get("employee_count") is not None
    }
    conflict = len(bands) > 1 or len(counts) > 1
    chosen = candidates[0] if candidates and not conflict else None
    return dict(
        employee_count=chosen.attributes.get("employee_count") if chosen else None,
        team_size_band=chosen.attributes["team_size_band"] if chosen else "unknown",
        team_size_evidence_status="conflicting"
        if conflict
        else chosen.verification_status
        if chosen
        else "team_size_unknown",
        team_size_evidence=[
            dict(
                source=o.source,
                source_url=o.source_url,
                observed_at=utc(o.observed_at).isoformat(),
                historical=o.attributes.get("historical", False),
                employee_count=o.attributes.get("employee_count"),
                band=o.attributes.get("team_size_band"),
                verification_status=o.verification_status,
            )
            for o in observations
            if o.attributes.get("team_size_band", "unknown") != "unknown"
        ][:20],
    )


def hiring_intelligence(jobs, observations, days=30, job_observations=()):
    instant, signals = now(), []
    by_job = {}
    for o in job_observations:
        by_job.setdefault(o.job_id, []).append(o)
    for job in jobs:
        meta = job.discovery_metadata or {}
        fresh = bool(
            job.last_observed_at
            and utc(job.last_observed_at) >= instant - timedelta(days=days)
        )
        expiry = meta.get("date_expires") or meta.get("expires_at")
        if expiry:
            from datetime import datetime

            try:
                fresh = (
                    fresh
                    and utc(datetime.fromisoformat(expiry.replace("Z", "+00:00")))
                    > instant
                )
            except (ValueError, TypeError):
                fresh = False
        if meta.get("is_expired") or meta.get("listing_status") == "closed":
            fresh = False
        current_board = any(
            o.source == "greenhouse"
            and utc(o.last_observed_at) >= instant - timedelta(days=days)
            and o.verification_status == "source_reported"
            for o in by_job.get(job.id, [])
        )
        confirmed = fresh and (
            current_board
            or meta.get("is_confirmed_current") is True
            and job.source_verification_status == "source_reported"
        )
        signals.append(
            dict(
                job_id=str(job.id),
                title=job.title,
                source=job.source_platform,
                evidence_url=job.job_url,
                posted_at=utc(job.date_posted).isoformat() if job.date_posted else None,
                observed_at=utc(job.last_observed_at).isoformat()
                if job.last_observed_at
                else None,
                fresh=fresh,
                hiring_status="hiring_confirmed"
                if confirmed
                else "hiring_possible"
                if fresh
                else "hiring_unknown",
                location=job.location,
                remote_policy=job.remote_type,
                verification_status=job.source_verification_status,
            )
        )
    statements = [
        o
        for o in observations
        if not o.attributes.get("historical")
        and utc(o.observed_at) >= instant - timedelta(days=days)
        and o.verification_status in {"source_reported", "human_confirmed"}
        and o.attributes.get("hiring_statement")
    ]
    latest = max(statements, key=lambda o: utc(o.observed_at), default=None)
    status = (
        "hiring_confirmed"
        if any(s["hiring_status"] == "hiring_confirmed" for s in signals)
        else "hiring_possible"
        if any(s["fresh"] for s in signals)
        else latest.attributes["hiring_statement"]
        if latest
        else "hiring_unknown"
    )
    return dict(
        hiring_status=status,
        hiring_evidence=signals,
        hiring_statement_evidence=[
            dict(
                source=o.source,
                evidence_url=o.source_url,
                observed_at=utc(o.observed_at).isoformat(),
                status=o.attributes["hiring_statement"],
            )
            for o in statements[:20]
        ],
    )
