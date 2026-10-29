"""Durable, bounded preparation of owner imports. No portal/mailbox transport.

The owner lock serializes ticks, daily reservations and Stop. Claims commit
before preparation; policy revisions fence delayed work. Browser actions remain
separately reviewed and Naukri submission is unsupported.
"""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.contracts import AutomationPolicy
from backend.app.local_agent.profile_confirmation import confirmation_matches
from backend.app.models.application_answer import CandidateResource
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.job import Job
from backend.app.services.applications.resume_selector import select_resume

KEY = "naukri_automation"
HEALTH = "naukri_worker_health"
DECISION = "nau_dec:"


async def record(session):
    row = await session.get(OwnerPreference, KEY, populate_existing=True)
    return row.value if row else {"state": "STOPPED", "revision": 0, "policy": None}


async def put(session, key, value):
    row = await session.get(OwnerPreference, key)
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=key, value=value))
    await session.flush()


async def context(session):
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.singleton_key == "primary")
        .execution_options(populate_existing=True)
    )
    confirmation = await session.get(OwnerPreference, "phase1_profile_confirmation")
    resources = (
        (
            await session.scalars(
                select(CandidateResource)
                .where(CandidateResource.candidate_profile_id == profile.id)
                .execution_options(populate_existing=True)
            )
        ).all()
        if profile
        else []
    )
    resume = select_resume(resources).selected
    return (
        profile,
        confirmation_matches(profile, confirmation.value if confirmation else {}),
        resume,
    )


async def validate_policy(session, policy):
    if policy.source == "gmail_job_alerts":
        from backend.app.execution.alert_email import PHASE54_GMAIL_INTAKE_READY

        if not PHASE54_GMAIL_INTAKE_READY:
            raise ToolDenied("gmail_intake_deferred_to_phase54")
    profile, confirmed, resume = await context(session)
    if not confirmed or profile.version != policy.profile_version:
        raise ToolDenied("confirmed_profile_version_required")
    if (
        not resume
        or resume.resource_id != policy.resume_resource_id
        or resume.resource_version != policy.resume_version
    ):
        raise ToolDenied("approved_primary_resume_changed_or_missing")
    if (
        profile.verified_experience_years is None
        or not policy.experience_min
        <= profile.verified_experience_years
        <= policy.experience_max
    ):
        raise ToolDenied("verified_experience_outside_policy")


async def require_enabled(session):
    value = await record(session)
    # An absent policy preserves the existing explicit on-demand workflow.
    if value["revision"] and value["state"] != "RUNNING":
        raise ToolDenied("naukri_automation_" + value["state"].lower())
    if (await store.configuration(session)).mode == "OFF":
        raise ToolDenied("execution_mode_off")


async def configure(session, data):
    await store.memory_row(session, lock=True)
    value = await record(session)
    if value["revision"] != data.expected_revision:
        raise ToolDenied("automation_revision_conflict")
    await validate_policy(session, data.policy)
    if data.policy.telegram_questions:
        from backend.app.core.config import get_settings

        settings = get_settings()
        if (
            not settings.TELEGRAM_BOT_TOKEN
            or not settings.TELEGRAM_OWNER_CHAT_ID
            or not settings.TELEGRAM_OWNER_USER_ID
        ):
            raise ToolDenied("approved_telegram_channel_required")
    # Editing authority always stops/fences old tasks; Start is a separate gesture.
    await fence(session, "stop")
    value.update(
        state="STOPPED",
        revision=value["revision"] + 1,
        policy=data.policy.model_dump(mode="json"),
        next_check_at=None,
    )
    await put(session, KEY, value)
    return value


async def fence(session, action):
    from backend.app.browser import chrome_profiles, extension_tasks

    job_ids = {
        str(i)
        for i in (
            await session.scalars(select(Job.id).where(Job.source_platform == "naukri"))
        ).all()
    }
    for row in await store.rows(session):
        if (
            row.value["platform"] == "naukri" or row.value["job_id"] in job_ids
        ) and row.value["state"] not in store.TERMINAL | {"PAUSED"}:
            await store.control(
                session, row.value["id"], "pause", row.value["revision"]
            )
    # Do not trust a browser task/plan to be associated with an execution intent.
    packet_ids = {
        str(i)
        for i in (
            await session.scalars(
                select(ApplicationPacket.id)
                .join(Job, ApplicationPacket.job_id == Job.id)
                .where(Job.source_platform == "naukri")
            )
        ).all()
    }
    reason = "global_stop" if action == "stop" else "owner_pause"
    for task in await extension_tasks.rows(session):
        if (
            task.value["application_id"] in packet_ids
            and task.value["state"] not in extension_tasks.TERMINAL
        ):
            # Preserve a stronger existing Stop when Pause follows it.
            task_reason = (
                "global_stop" if task.value.get("reason") == "global_stop" else reason
            )
            extension_tasks.move(
                session,
                task,
                "PAUSED",
                task_reason,
                plan_id=None,
                authorization_id=None,
                browser_connection="paused",
            )
    for plan in await chrome_profiles.records(session, "fill_plan:"):
        if plan.value.get("application_id") in packet_ids and plan.value.get(
            "state"
        ) in {"preview", "authorized"}:
            plan.value = {
                **plan.value,
                "state": "read_only",
                "approved_fields": [],
                "expires_at": (await instant(session)).isoformat(),
            }
    for command in await chrome_profiles.records(session, chrome_profiles.COMMAND):
        if (
            command.value["application_id"] in packet_ids
            and command.value["state"] not in chrome_profiles.TERMINAL
        ):
            command.value = {
                **command.value,
                "state": "outcome_unknown"
                if command.value["state"] in {"leased", "executing"}
                else "cancelled",
                "reason": reason,
                "version": command.value["version"] + 1,
            }


async def control(session, data):
    await store.memory_row(session, lock=True)
    value = await record(session)
    if value["revision"] != data.expected_revision:
        raise ToolDenied("automation_revision_conflict")
    if data.action == "start":
        if not value["policy"]:
            raise ToolDenied("bounded_preparation_policy_required")
        await validate_policy(session, AutomationPolicy.model_validate(value["policy"]))
        if value["state"] == "RUNNING":
            return value
        config = await store.configuration(session)
        if config.mode == "OFF":
            await store.configure(
                session, config.model_copy(update={"mode": "ON_DEMAND"})
            )
        state = "RUNNING"
    else:
        await fence(session, data.action)
        state = "PAUSED" if data.action == "pause" else "STOPPED"
    value.update(
        state=state,
        revision=value["revision"] + 1,
        next_check_at=None,
        source_next_at=None,
        source_lease=None,
        source_lease_until=None,
        controlled_at=(await instant(session)).isoformat(),
    )
    # Start does not resume any individually paused execution or browser task.
    await put(session, KEY, value)
    return value


def policy_reason(job, decision, policy):
    meta = job.discovery_metadata or {}
    if decision["state"] != "ELIGIBLE":
        return decision["reason"]
    if decision["title"].casefold() not in policy.allowed_roles:
        return "role_outside_policy"
    if (decision["employer"] or "").casefold() in policy.excluded_companies:
        return "excluded_company"
    if (
        meta.get("location") or job.location or ""
    ).casefold() not in policy.allowed_locations:
        return "location_outside_policy"
    lower, upper = meta.get("experience_min_years"), meta.get("experience_max_years")
    if (
        meta.get("data_provenance", {}).get("experience_requirement") != "required"
        or lower is None
        or upper is None
    ):
        return "required_experience_band_unknown"
    if lower < policy.experience_min or upper > policy.experience_max:
        return "job_experience_band_outside_policy"
    try:
        posted = datetime.fromisoformat(meta["date_posted"])
        if posted.tzinfo is None or not timedelta(0) <= datetime.now(
            timezone.utc
        ) - posted <= timedelta(days=policy.max_posting_age_days):
            return "posting_outside_freshness_policy"
    except (KeyError, TypeError, ValueError):
        return "posting_date_required"
    match = decision["match"]
    if (
        not meta.get("skills_required")
        or match["missing_skills"]
        or match["match_score"] < policy.minimum_match_score
        or match["negative_factors"]
    ):
        return "strict_skill_or_preference_match_required"
    # Explicit numeric experience band supersedes the legacy free-text field.
    # Size and unadvertised salary are informational when no such owner
    # restriction exists. salary_comparison/company_stage still block.
    if set(match["unknown_fields"]) - {
        "experience_suitability",
        "company_size",
        "salary",
    }:
        return "uncertain_match_requires_review"
    return None


async def tick(session):
    from backend.app.execution.naukri_review import review_jobs

    await store.memory_row(session, lock=True)
    now = await instant(session)
    await put(session, HEALTH, {"heartbeat_at": now.isoformat()})
    value = await record(session)
    if (
        value["state"] != "RUNNING"
        or (await store.configuration(session)).mode == "OFF"
    ):
        return
    if (
        value.get("next_check_at")
        and datetime.fromisoformat(value["next_check_at"]) > now
    ):
        return
    policy = AutomationPolicy.model_validate(value["policy"])
    value.update(
        last_check_at=now.isoformat(),
        next_check_at=(now + timedelta(seconds=policy.interval_seconds)).isoformat(),
    )
    try:
        await validate_policy(session, policy)
    except ToolDenied as exc:
        value["blocked_reason"] = str(exc)
        await put(session, KEY, value)
        return
    jobs_query = (
        select(Job).where(Job.source_platform == "naukri").order_by(Job.id).limit(100)
        .execution_options(populate_existing=True)
    )
    if value.get("cursor"):
        jobs_query = jobs_query.where(Job.id > UUID(value["cursor"]))
    jobs = list((await session.scalars(jobs_query)).all())
    value["cursor"] = str(jobs[-1].id) if len(jobs) == 100 else None
    today = now.date().isoformat()
    budget_key = "nau_budget:" + today
    budget = await session.get(OwnerPreference, budget_key)
    used = budget.value["reserved"] if budget else 0
    for job, decision in zip(jobs, await review_jobs(session, jobs), strict=True):
        reason = policy_reason(job, decision, policy)
        if not reason:
            existing = await session.get(
                OwnerPreference,
                store.PREFIX
                + str(uuid5(NAMESPACE_URL, "naukri:" + job.job_url.rsplit("-", 1)[-1])),
            )
            if existing:
                reason = "existing_intent_no_automatic_resume"
            elif used >= policy.max_preparations_per_day:
                reason = "daily_preparation_limit"
            else:
                intent = (await store.start(session, [job.id]))[0]
                row = await store.load(session, intent["id"])
                row.value = {**row.value, "automation_revision": value["revision"]}
                used += 1
        evidence = (job.discovery_metadata or {}).get("data_provenance", {})
        await put(
            session,
            DECISION + str(job.id),
            {
                **decision,
                "reason": reason or "bounded_preparation_queued",
                "eligible": policy_reason(job, decision, policy) is None,
                "policy_revision": value["revision"],
                "evaluated_at": now.isoformat(),
                "source": evidence.get("method", "owner_url"),
                "source_reference": evidence.get("reference"),
                "last_observation": evidence.get("owner_observed_at"),
            },
        )
    await put(session, budget_key, {"reserved": used, "day_timezone": "UTC"})
    value["blocked_reason"] = (
        "recurring_external_source_not_connected"
        if policy.source == "saved_owner_imports"
        else "email_vacancy_facts_require_owner_review"
    )
    await put(session, KEY, value)


async def execution_policy(session, row):
    """Recheck authority and changing facts after the committed claim."""
    if "automation_revision" not in row.value:
        return None
    from backend.app.execution.naukri_review import review_jobs

    value = await record(session)
    policy = AutomationPolicy.model_validate(value["policy"])
    await validate_policy(session, policy)
    job = await session.get(Job, UUID(row.value["job_id"]), populate_existing=True)
    if not job:
        raise ToolDenied("saved_naukri_job_required")
    decision = (await review_jobs(session, [job]))[0]
    reason = policy_reason(job, decision, policy)
    if reason:
        raise ToolDenied(reason)
    return policy


async def status(session):
    from backend.app.browser import chrome_profiles
    from backend.app.core.config import get_settings
    from backend.app.execution import alert_email

    now = await instant(session)
    value = await record(session)
    health = await session.get(OwnerPreference, HEALTH)
    heartbeat = health.value["heartbeat_at"] if health else None
    live = bool(
        heartbeat and (now - datetime.fromisoformat(heartbeat)).total_seconds() < 30
    )
    selected = (await chrome_profiles.selection(session))["profile_binding_id"]
    profile_row = (
        await session.get(OwnerPreference, chrome_profiles.PROFILE + selected)
        if selected
        else None
    )
    chrome = (
        chrome_profiles.public(profile_row.value, selected) if profile_row else None
    )
    decisions = [
        r.value
        for r in (
            await session.scalars(
                select(OwnerPreference).where(OwnerPreference.key.startswith(DECISION))
            )
        ).all()
    ]
    executions = [
        r.value for r in await store.rows(session) if r.value["platform"] == "naukri"
    ]
    packets = list(
        (
            await session.scalars(
                select(ApplicationPacket)
                .join(Job, Job.id == ApplicationPacket.job_id)
                .where(Job.source_platform == "naukri")
            )
        ).all()
    )
    source = value["policy"]["source"] if value["policy"] else "saved_owner_imports"
    blockers = [
        "naukri_browser_permission_not_verified",
        "naukri_submission_capability_not_verified",
        "locked_screen_acceptance_not_run",
    ]
    if source == "saved_owner_imports":
        blockers.insert(0, "recurring_external_source_not_connected")
    elif not alert_email.PHASE54_GMAIL_INTAKE_READY:
        blockers.insert(0, "gmail_intake_deferred_to_phase54")
    elif not get_settings().NAUKRI_ALERT_EMAILS_ENABLED:
        blockers.insert(0, "naukri_alert_email_activation_required")
    elif value.get("source_error"):
        blockers.insert(0, value["source_error"])
    elif not value.get("source_last_check_at"):
        blockers.insert(0, "job_alert_source_not_yet_observed")
    if not live:
        blockers.insert(0, "execution_worker_offline")
    if not chrome or chrome["status"] != "CONNECTED":
        blockers.append("selected_chrome_profile_offline_or_missing")
    if not get_settings().CHROME_PROFILE_COMMANDS_ENABLED:
        blockers.append("chrome_command_channel_disabled")
    elif chrome and not chrome["commands_enabled"]:
        blockers.append("selected_profile_command_opt_in_required")
    if value["policy"]:
        try:
            await validate_policy(
                session, AutomationPolicy.model_validate(value["policy"])
            )
        except ToolDenied as exc:
            blockers.insert(0, str(exc))
    if value.get("blocked_reason") and value["blocked_reason"] not in blockers:
        blockers.insert(0, value["blocked_reason"])
    profile, confirmed, resume = await context(session)
    alerts = []
    for row in (
        await session.scalars(
            select(OwnerPreference).where(
                OwnerPreference.key.startswith(alert_email.PREFIX)
            )
        )
    ).all():
        if row.value.get("expires_at") and row.value["expires_at"] <= now.isoformat():
            # Match the originating Gmail retention window; keep a dedup tombstone.
            row.value = {"id": row.value["id"], "state": "EXPIRED"}
        elif row.value.get("state") != "EXPIRED":
            alerts.append(row.value)
    return {
        **{k: v for k, v in value.items() if k != "source_lease"},
        "scope": "PARTIAL_PREPARATION",
        "source": source,
        "alert_candidates": alerts,
        "email_source_activation_available": bool(
            alert_email.PHASE54_GMAIL_INTAKE_READY
            and get_settings().NAUKRI_ALERT_EMAILS_ENABLED
        ),
        "chrome_channel_available": get_settings().CHROME_PROFILE_COMMANDS_ENABLED,
        "new_vacancy_discovery": False,
        "worker_online": live,
        "worker_heartbeat_at": heartbeat,
        "chrome_profile": chrome,
        "blockers": blockers,
        "last_observation": max(
            (d["last_observation"] for d in decisions if d.get("last_observation")),
            default=None,
        ),
        "counts": {
            "alert_candidates": len(alerts),
            "matching": sum(d["eligible"] for d in decisions),
            "prepared": sum(
                bool(e["packet_id"]) and not e.get("question_only") for e in executions
            ),
            # No genuine Naukri confirmation adapter exists. In particular,
            # fixture mock_employer receipts must never count as real.
            "submitted_confirmed": 0,
            "user_reported": sum(
                p.lifecycle_state == "user_reported_submitted" for p in packets
            ),
            "unknown": sum(
                p.lifecycle_state in {"submission_unknown", "submitting"}
                for p in packets
            ),
            "failed": sum(
                e["state"] in {"FAILED_FINAL", "FAILED_RETRYABLE"} for e in executions
            ),
            "manual_required": len(
                {d["id"] for d in decisions if d["state"] == "NEEDS_INPUT"}
                | {e["job_id"] for e in executions if e["state"] == "NEEDS_INPUT"}
            )
            + sum(a["state"] == "NEEDS_INPUT" for a in alerts),
        },
        "policy_context": {
            "profile_version": profile.version if profile and confirmed else None,
            "resume": resume.model_dump(mode="json") if resume else None,
        },
        "decisions": decisions,
        "stages": {
            "DISCOVERY": "email_candidates_require_review"
            if source == "gmail_job_alerts"
            else "external_source_blocked",
            "PREPARATION": value["state"],
            "FIELD_FILL": "separate_review_and_permission_required",
            "SUBMISSION": "unsupported",
            "PROVIDER_CONFIRMED": "independent_evidence_required",
        },
    }
