"""Bounded local preparation worker; never dispatches a Naukri submission."""

import asyncio
import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import Notification, OwnerPreference
from backend.app.execution import store
from backend.app.execution.naukri import reviewed_job_context
from backend.app.integrations.gmail.history import reviewed_history
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.services.applications.platforms.naukri import posting_unavailable
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher


def needs_owner_answer(field, now):
    if field.field_type == "file":
        return False
    expiry = field.provenance.answer_expires_at
    return bool(
        (field.required and not field.effective_answer) or (expiry and expiry <= now)
    )


def eligibility(job, profile, match):
    """Unknown/preferred criteria cannot become required or an auto-submit grant."""
    meta = job.discovery_metadata or {}
    provenance = meta.get("data_provenance", {})
    if posting_unavailable(job):
        return "REJECTED", "vacancy_closed_expired_or_invalid"
    required = provenance.get("experience_requirement") == "required"
    years, lower, upper = (
        profile.verified_experience_years,
        meta.get("experience_min_years"),
        meta.get("experience_max_years"),
    )
    if match.exclusion_reasons:
        return "REJECTED", "previous_application_or_owner_exclusion"
    if (
        required
        and lower is not None
        and years is not None
        and (years < lower or (upper is not None and years > upper))
    ):
        return "REJECTED", "required_experience_outside_verified_band"
    if required and (lower is None or years is None):
        return "NEEDS_INPUT", "required_experience_unknown"
    if not match.matched_skills or match.match_score < 50 or match.missing_skills:
        return "NEEDS_INPUT", "fit_requires_owner_review"
    if lower is None or years is None:
        return "NEEDS_INPUT", "experience_suitability_unknown"
    return "ELIGIBLE", "preparation_only_owner_review_required"


async def prepare(session, identity):
    row = await store.fenced(session, identity)
    from backend.app.execution import recurring

    try:
        policy = await recurring.execution_policy(session, row)
    except ToolDenied as exc:
        await store.control(session, row.value["id"], "pause", row.value["revision"])
        row.value = {**row.value, "diagnostic": str(exc)}
        return
    job = await session.get(Job, UUID(row.value["job_id"]), populate_existing=True)
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.singleton_key == "primary")
    )
    if not job or not profile:
        row.value = {
            **row.value,
            "state": "NEEDS_INPUT",
            "diagnostic": "candidate_or_job_missing",
            "lease_until": None,
        }
        return
    if await store.previously_applied(session, job):
        row.value = {
            **row.value,
            "state": "REJECTED",
            "revision": row.value["revision"] + 1,
            "diagnostic": "previous_application_or_unknown_submission",
            "lease_until": None,
        }
        await store.emit(
            session, row.value, "prior_application_excluded", await instant(session)
        )
        return
    if row.value["state"] == "DISCOVERED":
        await store.move(session, row, "MATCHED")
    if row.value["state"] == "MATCHED":
        company = await session.get(Company, job.company_id) if job.company_id else None
        job, company = reviewed_job_context(job, company)
        match = JobDiscoveryMatcher(session, await reviewed_history(session)).match(
            job, CandidateProfileRead.model_validate(profile), company
        )
        state, reason = eligibility(job, profile, match)
        if await store.previously_applied(session, job):
            state, reason = "REJECTED", "previous_application_or_unknown_submission"
        row.value = {
            **row.value,
            "profile_version": profile.version,
            "match": match.model_dump(),
        }
        await store.move(session, row, state, reason)
    if row.value["state"] in {"ELIGIBLE", "FAILED_RETRYABLE"}:
        await store.move(session, row, "PREPARING")
    if row.value["state"] == "PREPARING":
        service = ApplicationPacketService(session)
        existing_id = row.value["packet_id"] or await session.scalar(
            select(ApplicationPacket.id).where(
                ApplicationPacket.job_id == job.id,
                ApplicationPacket.candidate_profile_id == profile.id,
            )
        )
        packet = (
            await service.read(UUID(str(existing_id)))
            if existing_id
            else await service.create(
                job.id, CreatePacket(idempotency_key="exec_" + row.value["id"])
            )
        )
        row.value = {
            **row.value,
            "packet_id": str(packet.id),
            "profile_version": packet.candidate_profile_version,
        }
        if packet.readiness.stale or (
            policy
            and (
                not packet.snapshot.resume.selected
                or packet.snapshot.resume.selected.resource_id
                != policy.resume_resource_id
                or packet.snapshot.resume.selected.resource_version
                != policy.resume_version
            )
        ):
            await store.move(
                session, row, "NEEDS_INPUT", "stale_packet_or_unapproved_resume"
            )
            row.value = {**row.value, "lease_until": None}
            return
        await store.move(
            session,
            row,
            "NEEDS_INPUT"
            if packet.readiness.state
            in {"needs_input", "needs_resume", "needs_profile"}
            else "READY_FOR_REVIEW",
            packet.readiness.state,
        )
    row.value = {**row.value, "lease_until": None, "attempts": 0}
    await queue_policy_questions(session, row, policy)


async def queue_policy_questions(session, row, policy):
    if (
        not policy
        or not policy.telegram_questions
        or row.value["state"] != "NEEDS_INPUT"
        or not row.value["packet_id"]
    ):
        return
    from backend.app.execution import questions

    packet = await ApplicationPacketService(session).read(UUID(row.value["packet_id"]))
    if packet.readiness.stale:
        return
    for field in packet.fields:
        if needs_owner_answer(field, await instant(session)):
            try:
                async with session.begin_nested():
                    await questions.ask(session, row.value["id"], field.id)
            except (ToolDenied, ValueError):
                row.value = {**row.value, "diagnostic": "manual_question_required"}
    # Only a saved opt-in policy may queue these prompts. The separately
    # approved Telegram worker performs delivery using the existing outbox.


async def watch(session):
    """Scan only already imported data. Never poll a Naukri portal or mailbox."""
    await store.memory_row(session, lock=True)
    from backend.app.execution.recurring import require_enabled
    try:
        await require_enabled(session)
    except ToolDenied:
        return 0
    config = await store.configuration(session)
    if config.mode != "WATCH_AND_NOTIFY":
        return 0
    now = await instant(session)
    row = await session.get(OwnerPreference, "exec_watch:naukri")
    if row and row.value["next_at"] > now.isoformat():
        return 0
    state = {
        "next_at": (now + timedelta(seconds=config.interval_seconds)).isoformat(),
        "heartbeat_at": now.isoformat(),
    }
    if row:
        row.value = state
    else:
        session.add(OwnerPreference(key="exec_watch:naukri", value=state))
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.singleton_key == "primary")
    )
    if not profile:
        return 0
    count = 0
    jobs = (
        await session.scalars(
            select(Job)
            .where(Job.source_platform == "naukri")
            .order_by(Job.created_at.desc())
            .limit(100)
        )
    ).all()
    history = await reviewed_history(session)
    for job in jobs:
        if await store.previously_applied(session, job):
            continue
        company = await session.get(Company, job.company_id) if job.company_id else None
        job, company = reviewed_job_context(job, company)
        match = JobDiscoveryMatcher(session, history).match(
            job, CandidateProfileRead.model_validate(profile), company
        )
        if eligibility(job, profile, match)[0] != "ELIGIBLE":
            continue
        key = "naukri_watch:" + str(job.id) + ":" + str(profile.version)
        if await session.scalar(
            select(Notification.id).where(Notification.dedup_key == key)
        ):
            continue
        session.add(
            Notification(
                dedup_key=key,
                kind="job_match",
                title="Naukri saved opportunity",
                body=f"{job.title}: imported facts match saved preferences; review vacancy and eligibility.",
                href="/jobs/" + str(job.id),
            )
        )
        count += 1
    return count


class ExecutionWorker:
    def __init__(self, factory):
        self.factory = factory

    async def tick(self):
        from backend.app.execution.alert_email import poll

        await poll(self.factory)
        async with self.factory() as session, session.begin():
            from backend.app.execution import recurring

            await recurring.tick(session)
            await watch(session)
            now = await instant(session)
            automation = await recurring.record(session)
            for row in await store.rows(session):
                if (
                    row.value["state"] not in {"READY_FOR_REVIEW", "NEEDS_INPUT"}
                    or not row.value["packet_id"]
                ):
                    continue
                packet = await ApplicationPacketService(session).read(
                    UUID(row.value["packet_id"])
                )
                if (
                    row.value["state"] == "READY_FOR_REVIEW"
                    and not packet.readiness.stale
                    and any(needs_owner_answer(field, now) for field in packet.fields)
                ):
                    await store.move(
                        session, row, "NEEDS_INPUT", "owner_question_approval_required"
                    )
                if (
                    automation["state"] == "RUNNING"
                    and row.value.get("automation_revision") == automation["revision"]
                ):
                    from backend.app.execution.contracts import AutomationPolicy

                    policy = AutomationPolicy.model_validate(automation["policy"])
                    await queue_policy_questions(session, row, policy)
            identity = await store.claim(session)
        if not identity:
            return None
        try:
            async with self.factory() as session, session.begin():
                await prepare(session, identity)
        except ToolDenied:
            return None
        except Exception:
            async with self.factory() as session, session.begin():
                try:
                    row = await store.fenced(session, identity)
                except ToolDenied:
                    return None
                now = await instant(session)
                row.value = {
                    **row.value,
                    "state": "FAILED_RETRYABLE",
                    "revision": row.value["revision"] + 1,
                    "diagnostic": "preparation_failed",
                    "lease_until": None,
                    "available_at": (now + timedelta(seconds=60)).isoformat(),
                }
                await store.emit(session, row.value, "preparation_failed", now)
        return identity


async def serve(factory, stop):
    worker = ExecutionWorker(factory)
    delay = 5
    while not stop.is_set():
        try:
            await worker.tick()
            delay = 5
        except Exception:
            # Heartbeats go stale during outages; never report an alive thread as
            # a successful DB check. No exception details containing URLs/secrets.
            logging.getLogger(__name__).warning(
                "Execution worker tick failed; retrying in %s seconds", delay
            )
            delay = min(60, delay * 2)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
