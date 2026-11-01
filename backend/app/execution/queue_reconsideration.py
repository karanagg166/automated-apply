"""Recheck never-attempted observations when the owner changes factual filters.

An existing identity may receive a new ordinary listing read. Neither retained
facts nor a policy edit grants preparation, a packet, or a browser write.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    OwnerPreference,
)
from backend.app.execution import application_queue as queue
from backend.app.execution import store
from backend.app.execution.queue_contracts import QueuePolicy
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.services.discovery_budget import insert_for

KEY = "apply_filter_recheck"
BATCH = 10
REASONS = frozenset({
    "posting_outside_age_limit", "posting_age_requires_review", "posting_timestamp_unknown",
    "applicant_limit_reached", "applicant_count_unknown_skip", "applicant_count_requires_review",
    "required_experience_outside_verified_band", "verified_experience_requirements_required",
    "current_profile_preferences_or_required_skills_exclude_job", "minimum_match_score_required",
    "advertised_experience_outside_platform_preferences", "advertised_salary_outside_platform_preferences",
    "salary_comparison_requires_review", "uncertain_job_requirements_require_review",
    "verified_profile_context_changed",
})


def filters(policy):
    platform = policy.platforms["naukri"]
    effective = queue.limits(policy, "naukri")
    effective.pop("daily_cap")
    return {"limits": effective, "enabled": platform.enabled, "sources": platform.sources,
            "preferences_mode": platform.preferences_mode,
            "preferences": platform.preferences.model_dump(mode="json")}


async def request(session, reason):
    value = {"id": str(uuid4()), "status": "pending", "cursor": None, "reason": reason,
             "requested_at": (await instant(session)).isoformat(), "checked": 0, "fresh_reads": 0}
    await session.execute(insert_for(session)(OwnerPreference).values(key=KEY, value=value).on_conflict_do_update(
        index_elements=[OwnerPreference.key], set_={"value": value, "updated_at": func.now()},
    ))


async def notify_applicant_review(session, policy):
    effective = queue.limits(policy, "naukri")
    threshold = effective["applicant_limit"]
    if threshold is None or effective["unknown_applicants"] != "needs_review":
        return
    key = f"naukri_applicant_question:{threshold}"
    values = {"dedup_key": key, "kind": "automation_policy_question",
              "title": "Choose how Naukri applicant estimates are handled",
              "body": (f"A label such as 100+ gives a minimum, not proof of fewer than {threshold:,} applicants. "
                       "Your current rule holds these jobs. In Naukri queue settings you can keep review, skip, "
                       "or explicitly allow lower-bound labels below your threshold while reviewing missing counts. "
                       "Actual counts may exceed the threshold; all other eligibility checks still apply."),
              "href": "/naukri"}
    result = await session.execute(insert_for(session)(Notification).values(**values).on_conflict_do_update(
        index_elements=[Notification.dedup_key], set_={**values, "read_at": None},
        where=Notification.kind == "automation_policy_resolved",
    ).returning(Notification.id))
    identity = result.scalar_one_or_none()
    if identity:
        await session.execute(insert_for(session)(NotificationDelivery).values(
            notification_id=identity, channel="in_app", status="available_in_app", attempt_count=1,
        ).on_conflict_do_nothing(index_elements=["notification_id", "channel"]))


async def resolve_applicant_review(session, previous, current):
    before, after = queue.limits(previous, "naukri"), queue.limits(current, "naukri")
    if (before["unknown_applicants"] != "needs_review" or before["applicant_limit"] is None
            or (after["unknown_applicants"] == "needs_review" and after["applicant_limit"] == before["applicant_limit"])):
        return
    await session.execute(update(Notification).where(
        Notification.dedup_key == f"naukri_applicant_question:{before['applicant_limit']}",
        Notification.kind == "automation_policy_question",
    ).values(kind="automation_policy_resolved", title="Naukri applicant-count policy updated",
             body="Your saved applicant-count rule changed. Check the current Naukri queue policy; other filters and submission prerequisites remain enforced."))


async def tick(session):
    hint = await session.get(OwnerPreference, KEY, populate_existing=True)
    if not hint or hint.value.get("status") != "pending":
        return False
    if hint.value.get("retry_after") and datetime.fromisoformat(hint.value["retry_after"]) > datetime.now(timezone.utc):
        return False
    config = await queue.configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    if config["state"] != "RUNNING" or not policy.platforms["naukri"].enabled:
        return False
    await store.memory_row(session, lock=True)
    config = await queue.configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    marker = await session.get(OwnerPreference, KEY, populate_existing=True, with_for_update=True)
    if (config["state"] != "RUNNING" or not policy.platforms["naukri"].enabled
            or not marker or marker.value.get("status") != "pending"):
        return False
    from backend.app.execution.recurring import context

    profile, confirmed, _ = await context(session)
    if not confirmed:
        return False
    query = select(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX),
        OwnerPreference.value["platform"].as_string() == "naukri",
        OwnerPreference.value["stage"].as_string().in_(["SKIPPED", "NEEDS_INPUT"]),
        OwnerPreference.value["reason"].as_string().in_(REASONS),
    )
    state = dict(marker.value)
    if state.get("cursor"):
        query = query.where(OwnerPreference.key > state["cursor"])
    rows = (await session.scalars(query.order_by(OwnerPreference.key).limit(BATCH))).all()
    if not rows:
        marker.value = {**state, "status": "complete", "completed_at": (await instant(session)).isoformat()}
        await session.flush()
        return False
    requisitions = {r.value["requisition"] for r in rows}
    receipts = set((await session.scalars(select(OwnerPreference.key).where(OwnerPreference.key.in_(
        [prefix + req for req in requisitions for prefix in ("naukri_receipt:", "naukri_worker_receipt:")]
    )))).all())
    jobs = (await session.scalars(select(Job).where(Job.source_platform == "naukri", or_(
        *(Job.job_url.like("%-" + req + suffix) for req in requisitions for suffix in ("", "/"))
    )))).all()
    terminal_jobs = set((await session.scalars(select(ApplicationPacket.job_id).where(
        ApplicationPacket.job_id.in_([job.id for job in jobs]),
        ApplicationPacket.lifecycle_state.in_([
            "user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown",
        ]),
    ))).all()) if jobs else set()
    excluded = {req for req in requisitions if any(prefix + req in receipts for prefix in (
        "naukri_receipt:", "naukri_worker_receipt:",
    ))}
    for job in jobs:
        if (job.id in terminal_jobs or job.status in {"applied", "submitted"}
                or getattr(job, "application_status", None) in {"applied", "submitted", "interview", "offer", "applied_manually", "applied_verified"}
                or (job.discovery_metadata or {}).get("data_provenance", {}).get("posting_status") == "already_applied"):
            excluded.update(req for req in requisitions if job.job_url.rstrip("/").endswith("-" + req))
    lookup = {str(job.id): job for job in jobs}
    companies = {company.id: company for company in (await session.scalars(select(Company).where(
        Company.id.in_({job.company_id for job in jobs if job.company_id}),
    ))).all()} if jobs else {}
    pending = await session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith(queue.PREFIX), OwnerPreference.value["stage"].as_string().not_in(queue.TERMINAL),
    ))
    now, changed = await instant(session), []
    for row in rows:
        before = dict(row.value)
        if (before.get("admitted_actions") or before.get("packet_id") or before.get("form_pending")
                or before.get("lease_until") or before["status"] not in {"waiting", "complete"}
                or before["requisition"] in excluded or not before.get("facts")
                or before.get("source") not in policy.platforms["naukri"].sources):
            state["cursor"] = row.key
            continue
        value = {**before, "profile_version": None}
        reason = queue.listing_exclusion(value["facts"], queue.limits(policy, "naukri"), now)
        if not reason:
            job = lookup.get(value.get("job_id"))
            if job:
                try:
                    queue.check_eligibility(value, policy, job, companies.get(job.company_id), profile, now)
                except ToolDenied as exc:
                    reason = str(exc)
            else:
                lower, upper = value["facts"].get("experience_min"), value["facts"].get("experience_max")
                years = profile.verified_experience_years
                if lower is None or upper is None or years is None:
                    reason = "verified_experience_requirements_required"
                elif not lower <= years <= upper:
                    reason = "required_experience_outside_verified_band"
        if not reason and before["stage"] in queue.TERMINAL and pending >= policy.max_pending:
            state["retry_after"] = (now + timedelta(seconds=60)).isoformat()
            break  # Do not move the cursor beyond an eligible blocked slot.
        state["cursor"] = row.key
        if reason:
            queue.eligibility_hold(value, reason)
        else:
            value.update(stage="DISCOVERED", status="queued", operation="inspect_job", reason=None,
                         binding=None, lease_token=None, lease_until=None, available_at=now.isoformat())
            state["fresh_reads"] += 1
        pending += int(value["stage"] not in queue.TERMINAL) - int(before["stage"] not in queue.TERMINAL)
        value.update(revision=before["revision"] + 1, policy_revision=config["revision"], updated_at=now.isoformat(),
                     last_filter_recheck={"request_id": state["id"], "profile_version": profile.version,
                                          "policy_revision": config["revision"], "retained_facts_only": True})
        row.value = value
        state["checked"] += 1
        changed.append(value)
    await session.flush()
    await queue.events_batch(session, changed, "owner_filter_change_rechecked", now)
    marker.value = state
    await session.flush()
    return bool(changed)
