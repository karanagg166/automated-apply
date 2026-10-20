"""On-demand in-app events. No background task or external delivery is started."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    OwnerPreference,
)
from backend.app.dashboard.schemas import NotificationPreferences
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.app.models.outreach import OutreachLog
from backend.app.services.discovery_budget import insert_for


async def preferences(session):
    item = await session.get(OwnerPreference, "notifications")
    return NotificationPreferences.model_validate(item.value if item else {})


def notification_window(prefs, now=None):
    if prefs.paused or not prefs.in_app:
        return "paused"
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(prefs.timezone))
    start, end, hour = prefs.quiet_start, prefs.quiet_end, current.hour
    quiet = (start <= hour < end if start < end else (hour >= start or hour < end) if start != end else False)
    return "quiet_hours" if quiet else "available"


async def synchronize(session, *, automation=False):
    if automation and await session.get(OwnerPreference, "notifications") is None:
        return {"status": "awaiting_in_app_opt_in", "created": 0, "external_deliveries": 0}
    prefs = await preferences(session)
    current = datetime.now(timezone.utc).astimezone(ZoneInfo(prefs.timezone))
    window = notification_window(prefs)
    if window != "available":
        return {"status": window, "created": 0}
    events = []
    from backend.app.resume_sync.models import ResumeDriveSource, ResumeProfileReview

    source = await session.get(ResumeDriveSource, "primary")
    if source and source.latest_version_id and source.latest_version_id != source.active_version_id:
        review = await session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == source.latest_version_id))
        events.append((f"resume_review:{source.latest_version_id}:{review.review_cycle}", "resume_review",
                       "A resume version needs your review",
                       "Review the private PDF and profile differences before activating this version.", "/profile"))
    jobs = (
        await session.scalars(
            select(Job)
            .where(Job.match_score >= prefs.minimum_job_score)
            .order_by(Job.created_at.desc())
            .limit(100)
        )
    ).all()
    approved = True
    if automation:
        from backend.app.automation.models import AutomationExecution
        from backend.app.automation.store import (
            approved_profile,
            configuration,
            current_matches,
            schedule,
        )

        config = configuration(await schedule(session))
        approved = bool(await approved_profile(session, config))
        matches = await current_matches(session, config)
        ids = [m.job_id for m in matches if m.result["match_score"] >= prefs.minimum_job_score
               and not m.result.get("exclusion_reasons")]
        jobs = (await session.scalars(select(Job).where(Job.id.in_(ids)))).all() if ids else []
        if not approved:
            events.append((f"automation_profile:{config.approved_profile_id}:{config.approved_profile_version}",
                           "stale_match_profile", "Matching needs your review",
                           "Approve the current saved profile to refresh personalized results.", "/discover"))
        if prefs.automation_failures:
            failures = (await session.scalars(select(AutomationExecution).where(
                AutomationExecution.state.in_(["failed", "blocked", "partial"]),
            ).order_by(AutomationExecution.created_at.desc()).limit(50))).all()
            # One per source and owner-local day keeps repeated failures quiet.
            for failure in failures:
                occurred = (failure.finished_at or failure.created_at).replace(tzinfo=timezone.utc) if (failure.finished_at or failure.created_at).tzinfo is None else (failure.finished_at or failure.created_at)
                failure_day = occurred.astimezone(ZoneInfo(prefs.timezone)).date()
                events.append((f"automation_failure:{failure.source}:{failure_day}", "scheduled_discovery_failed",
                               "Discovery needs attention", "Review the execution history and source cooldown before retrying.", "/discover"))
        reviewable = await session.scalar(select(Job.id).where(
            Job.status == "discovered",
        ).limit(1))
        if reviewable and not jobs:
            events.append((f"automation_review:{current.date()}", "jobs_awaiting_review", "Saved opportunities await review",
                           "Inspect listing evidence before shortlisting or preparing an application.", "/jobs"))
    for job in jobs:
        events.append(
            (
                f"job:{job.id}",
                "high_match_job",
                "A matching opportunity is ready",
                "Review the saved job and its source evidence.",
                "/jobs",
            )
        )
    packets = (
        await session.scalars(
            select(ApplicationPacket)
            .where(
                ApplicationPacket.lifecycle_state.in_(
                    ["ready_for_review", "needs_input"]
                )
            )
            .limit(100)
        )
    ).all()
    for packet in packets:
        events.append(
            (
                f"packet:{packet.id}:{packet.revision}",
                "application_review",
                "An application needs your review",
                "Open the packet to review fields and missing information.",
                "/applications",
            )
        )
    drafts = (
        await session.scalars(
            select(OutreachLog)
            .where(OutreachLog.approval_status == "draft_created")
            .limit(100)
        )
    ).all()
    for draft in drafts:
        events.append(
            (
                f"draft:{draft.id}:{draft.draft_revision}",
                "outreach_review",
                "An outreach draft needs approval",
                "Review the recipient, evidence and exact message before approving.",
                "/outreach",
            )
        )
    if prefs.daily_digest:
        events.append(
            (
                f"digest:{current.date()}",
                "daily_summary",
                "Your daily review",
                f"{len(jobs)} saved high-match jobs and {len(packets)} packets awaiting attention (bounded to 100 each).",
                "/",
            )
        )
    from backend.app.models.contact_enrichment import ContactEvidence
    from backend.app.models.startup import ProviderConnectionCheck

    for evidence in (
        await session.scalars(
            select(ContactEvidence)
            .where(
                ContactEvidence.user_confirmed.is_(True),
                ContactEvidence.expires_at > datetime.now(timezone.utc),
            )
            .order_by(ContactEvidence.collected_at.desc())
            .limit(100)
        )
    ).all():
        events.append(
            (
                f"contact:{evidence.id}",
                "contact_evidence_updated",
                "Professional evidence was updated",
                "Review identity, employer and mailbox evidence before outreach.",
                "/people",
            )
        )
    for check in (
        await session.scalars(
            select(ProviderConnectionCheck)
            .where(
                ProviderConnectionCheck.state.in_(
                    ["failed", "rate_limited", "authorization_required"]
                )
            )
            .order_by(ProviderConnectionCheck.checked_at.desc())
            .limit(50)
        )
    ).all():
        events.append(
            (
                f"provider:{check.id}",
                "provider_connection_failed",
                "A provider needs attention",
                "Review connection health, permissions and recorded failure details.",
                "/connections",
            )
        )
    from backend.app.services.startup_discovery.schemas import StartupFilters
    from backend.app.services.startup_discovery.service import StartupDiscoveryService

    partial_errors = []
    try:
        matching_companies = set()
        if automation and approved:
            cached = await current_matches(session, config)
            matching_ids = [m.job_id for m in cached if m.result["match_score"] >= prefs.minimum_startup_score
                            and not m.result.get("exclusion_reasons")]
            matching_companies = set((await session.scalars(select(Job.company_id).where(Job.id.in_(matching_ids)))).all())
        startup_scan = await StartupDiscoveryService(session).search(
            StartupFilters(
                max_employees=200 if automation else None,
                include_unknown_size=not automation,
                minimum_score=0 if automation else prefs.minimum_startup_score,
                use_profile=approved and not automation, limit=100
            ),
            company_ids=list(matching_companies) if automation else None,
        )
        for startup in startup_scan["startups"]:
            if not approved:
                continue
            if automation and (startup["company_id"] not in {str(c) for c in matching_companies}
                               or startup["hiring_status"] == "hiring_unknown"):
                continue
            events.append(
                (
                    f"startup:{startup['company_id']}",
                    "new_matching_startup",
                    "A saved team matches your profile",
                    "Review the startup's hiring, team-size and technology evidence.",
                    "/startups",
                )
            )
    except ValueError:
        partial_errors.append(
            "Startup alert scan needs narrower saved sources; other events remain available"
        )
    created = 0
    for key, kind, title, body, href in events:
        result = await session.execute(
            insert_for(session)(Notification)
            .values(dedup_key=key, kind=kind, title=title, body=body, href=href)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(Notification.id)
        )
        notification_id = result.scalar_one_or_none()
        if notification_id is not None:
            created += 1
            await session.execute(
                insert_for(session)(NotificationDelivery)
                .values(
                    notification_id=notification_id,
                    channel="in_app",
                    status="available_in_app",
                    attempt_count=1,
                )
                .on_conflict_do_nothing(index_elements=["notification_id", "channel"])
            )
    return {
        "status": "partial_results" if partial_errors else "synchronized",
        "created": created,
        "external_deliveries": 0,
        "errors": partial_errors,
    }
