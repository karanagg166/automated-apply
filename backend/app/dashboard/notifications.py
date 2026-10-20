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


def notification_window(prefs):
    if prefs.paused or not prefs.in_app:
        return "paused"
    current = datetime.now(timezone.utc).astimezone(ZoneInfo(prefs.timezone))
    start, end, hour = prefs.quiet_start, prefs.quiet_end, current.hour
    quiet = (start <= hour < end if start < end else (hour >= start or hour < end) if start != end else False)
    return "quiet_hours" if quiet else "available"


async def synchronize(session):
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
            .where(Job.match_score >= 75)
            .order_by(Job.created_at.desc())
            .limit(100)
        )
    ).all()
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
        matches = await StartupDiscoveryService(session).search(
            StartupFilters(
                max_employees=None, minimum_score=70, use_profile=True, limit=100
            )
        )
        for startup in matches["startups"]:
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
