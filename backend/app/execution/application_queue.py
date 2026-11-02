"""Durable application messages using the existing private PostgreSQL store.

One owner fence serializes claims, budget admission and revocation. No broker,
new pool, DDL, portal transport or implicit submission grant is introduced.
"""

import hashlib
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.naukri import normalized_url
from backend.app.execution.queue_contracts import QueuePolicy

POLICY_KEY = "application_queue_policy"
PREFIX = "apply_work:"
EVENT = "apply_event:"
TERMINAL = {"SUBMITTED_RECORDED", "SUBMITTED_CONFIRMED", "FAILED_FINAL", "SKIPPED"}
WRITES = {"apply", "answer", "upload_resume", "answer_questionnaire"}

FILTER_HOLD_REASONS = frozenset({
    "posting_outside_age_limit", "posting_age_requires_review", "posting_timestamp_unknown",
    "applicant_limit_reached", "applicant_count_unknown_skip", "applicant_count_requires_review",
    "required_experience_outside_verified_band", "verified_experience_requirements_required",
    "current_profile_preferences_or_required_skills_exclude_job", "minimum_match_score_required",
    "advertised_experience_outside_platform_preferences", "advertised_salary_outside_platform_preferences",
    "salary_comparison_requires_review", "uncertain_job_requirements_require_review",
    "verified_profile_context_changed",
})


def uses_capacity(value):
    """Filter-only observation holds are history, not active application work."""
    if value["stage"] in TERMINAL:
        return False
    inert_filter_hold = (
        value["stage"] == "NEEDS_INPUT" and value["status"] == "waiting"
        and value.get("reason") in FILTER_HOLD_REASONS
        and value.get("admitted_actions") == []
        and not any(value.get(name) for name in ("packet_id", "form_pending", "lease_until"))
    )
    return not inert_filter_hold


def capacity_condition():
    """SQL equivalent of uses_capacity; malformed or unknown work stays bounded."""
    value = OwnerPreference.value
    return and_(value["stage"].as_string().not_in(TERMINAL), or_(
        func.coalesce(value["stage"].as_string(), "unknown") != "NEEDS_INPUT",
        func.coalesce(value["status"].as_string(), "unknown") != "waiting",
        func.coalesce(value["reason"].as_string(), "unknown").not_in(FILTER_HOLD_REASONS),
        value["packet_id"].as_string().is_not(None),
        value["lease_until"].as_string().is_not(None),
        value["form_pending"].as_boolean().is_(True),
        func.coalesce(value["admitted_actions"].as_string(), "unknown") != "[]",
    ))


async def configuration(session):
    await session.flush()
    row = await session.get(OwnerPreference, POLICY_KEY, populate_existing=True)
    return dict(row.value) if row else {
        "revision": 0, "state": "STOPPED", "policy": QueuePolicy().model_dump(mode="json")
    }


async def put(session, key, value):
    row = await session.get(OwnerPreference, key)
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=key, value=value))
    await session.flush()


async def items(session, *, active_only=False):
    await session.flush()
    query = select(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX)
    )
    if active_only:
        query = query.where(OwnerPreference.value["stage"].as_string().not_in(TERMINAL))
    return list((await session.scalars(query.order_by(
        OwnerPreference.created_at, OwnerPreference.key
    ).execution_options(populate_existing=True))).all())


async def event(session, value, name):
    identity = str(uuid5(NAMESPACE_URL, f"queue:{value['id']}:{value['revision']}:{name}"))
    await put(session, EVENT + identity, {
        "id": identity, "queue_id": value["id"], "platform": value["platform"],
        "stage": value["stage"], "event": name,
        "at": (await instant(session)).isoformat(), "delivered": False,
    })


async def events_batch(session, values, name, now=None):
    """Publish state-transition outbox records in the caller's transaction."""
    if not values:
        return
    from backend.app.services.discovery_budget import insert_for

    now = now or await instant(session)
    records = []
    for value in values:
        identity = str(uuid5(NAMESPACE_URL, f"queue:{value['id']}:{value['revision']}:{name}"))
        records.append({"key": EVENT + identity, "created_at": now, "updated_at": now,
                        "value": {"id": identity, "queue_id": value["id"], "platform": value["platform"],
                                  "stage": value["stage"], "event": name,
                                  "at": now.isoformat(), "delivered": False}})
    await session.execute(insert_for(session)(OwnerPreference).values(records).on_conflict_do_nothing(index_elements=[OwnerPreference.key]))


async def fence(session, reason):
    sync = await session.get(OwnerPreference, "apply_profile_sync:naukri", populate_existing=True)
    if sync:
        value = dict(sync.value)
        value.pop("approved_summary", None)
        sync.value = {**value, "status": "idle", "lease_token": None, "lease_until": None,
                      "revision": value["revision"] + 1, "last_error": reason}
    search = await session.get(OwnerPreference, "apply_search:naukri", populate_existing=True)
    if search:
        search.value = {**search.value, "status": "idle", "lease_token": None, "lease_until": None,
                        "next_at": None, "revision": search.value["revision"] + 1, "last_error": reason}
    changed = []
    # Unattempted input holds have no outstanding authority to revoke. The
    # global state/revision fences every later claim; rewriting their full
    # retained descriptions and outbox records makes Stop grow with history.
    # Keep packet/form/action/lease-bearing or malformed records in the fence.
    value = OwnerPreference.value
    candidates = select(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX),
        value["stage"].as_string().not_in(TERMINAL),
        or_(value["stage"].as_string() != "NEEDS_INPUT",
            value["status"].as_string() != "waiting",
            value["packet_id"].as_string().is_not(None),
            value["lease_until"].as_string().is_not(None),
            value["form_pending"].as_boolean().is_(True),
            func.coalesce(value["admitted_actions"].as_string(), "unknown") != "[]"),
    ).execution_options(populate_existing=True)
    for row in (await session.scalars(candidates)).all():
        value = dict(row.value)
        if value["stage"] in TERMINAL:
            continue
        if value["status"] == "unknown":
            continue  # Never turn an uncertain action into resumable work.
        uncertain = value["status"] == "executing" and value["operation"] in WRITES
        if value["stage"] != "PAUSED":
            value["paused_context"] = {k: value[k] for k in ("stage", "status", "operation", "reason")}
        value.update(
            stage="SUBMISSION_UNKNOWN" if uncertain else "PAUSED",
            status="unknown" if uncertain else "waiting",
            reason=reason, revision=value["revision"] + 1,
            lease_token=None, lease_until=None,
        )
        row.value = value
        changed.append(value)
    await session.flush()
    await events_batch(session, changed, "fenced")


async def configure(session, data):
    await store.memory_row(session, lock=True)
    current = await configuration(session)
    if current["revision"] != data.expected_revision:
        raise ToolDenied("queue_policy_revision_conflict")
    from backend.app.execution.naukri_automatic import require_policy

    await require_policy(session, data.policy)
    from backend.app.execution.queue_reconsideration import (
        filters,
        request,
        resolve_applicant_review,
    )

    filters_changed = filters(QueuePolicy.model_validate(current["policy"])) != filters(data.policy)
    await fence(session, "queue_policy_changed")
    value = {**current, "revision": current["revision"] + 1,
             "state": "PAUSED" if current["state"] == "RUNNING" else current["state"],
             "policy": data.policy.model_dump(mode="json")}
    await put(session, POLICY_KEY, value)
    await resolve_applicant_review(session, QueuePolicy.model_validate(current["policy"]), data.policy)
    if filters_changed:
        await request(session, "owner_policy_filters_changed")
    return value


async def control(session, data):
    await store.memory_row(session, lock=True)
    current = await configuration(session)
    if current["revision"] != data.expected_revision:
        raise ToolDenied("queue_policy_revision_conflict")
    if data.action == "start":
        if (await store.configuration(session)).mode == "OFF":
            raise ToolDenied("execution_mode_off")
        policy = QueuePolicy.model_validate(current["policy"])
        if not any(p.enabled for p in policy.platforms.values()):
            raise ToolDenied("enabled_platform_required")
        from backend.app.execution.naukri_automatic import require_policy

        await require_policy(session, policy)
        state = "RUNNING"
        changed = []
        paused_rows = select(OwnerPreference).where(
            OwnerPreference.key.startswith(PREFIX),
            OwnerPreference.value["stage"].as_string() == "PAUSED",
        ).execution_options(populate_existing=True)
        for row in (await session.scalars(paused_rows)).all():
            v = dict(row.value)
            if v["stage"] == "PAUSED" and v["reason"] in {"owner_pause", "global_stop", "queue_policy_changed"}:
                previous = v.get("paused_context", {})
                waiting = previous.get("status") == "waiting"
                v.update(stage=previous.get("stage", "DISCOVERED"),
                         status="waiting" if waiting else "queued",
                         operation=previous.get("operation", "inspect_job"),
                         reason=previous.get("reason"), revision=v["revision"] + 1)
                if not waiting and v.get("form_pending"):
                    v.update(operation="refresh_questionnaire_profile", stage="QUESTIONS")
                elif not waiting and v["operation"] in WRITES:
                    v.update(operation="inspect_profile" if v.get("account_sha256") and not v.get("admitted_actions") else "inspect_application", stage="VERIFYING")
                row.value = v
                changed.append(v)
        await session.flush()
        await events_batch(session, changed, "resumed_for_fresh_inspection")
    else:
        await fence(session, "global_stop" if data.action == "stop" else "owner_pause")
        from backend.app.execution import recurring

        # The dashboard Stop also fences the legacy preparation/form channel.
        await recurring.fence(session, data.action)
        legacy = await recurring.record(session)
        if legacy["revision"]:
            legacy.update(state="STOPPED" if data.action == "stop" else "PAUSED",
                          revision=legacy["revision"] + 1)
            await recurring.put(session, recurring.KEY, legacy)
        state = "STOPPED" if data.action == "stop" else "PAUSED"
    current.update(state=state, revision=current["revision"] + 1)
    await put(session, POLICY_KEY, current)
    return current


def limits(policy, platform):
    settings = policy.platforms[platform]
    global_ = policy.global_limits
    return {
        "daily_cap": settings.limits.daily_cap if settings.cap_mode == "custom" else global_.daily_cap,
        "max_job_age_days": settings.limits.max_job_age_days if settings.age_mode == "custom" else global_.max_job_age_days,
        "applicant_limit": settings.limits.applicant_limit if settings.applicants_mode == "custom" else global_.applicant_limit,
        "unknown_applicants": settings.limits.unknown_applicants if settings.applicants_mode == "custom" else global_.unknown_applicants,
        "minimum_match_score": global_.minimum_match_score,
    }


def listing_exclusion(facts, effective, now):
    try:
        if facts.get("posted_at"):
            posted = datetime.fromisoformat(facts["posted_at"])
            if posted.tzinfo is None:
                return "posting_timestamp_unknown"
        elif facts.get("posted_date"):
            # Exact time and source timezone are unknown. Use the earliest
            # possible instant across civil offsets (-12..+14) for eligibility,
            # never persist that bound as an actual provider posting timestamp.
            from datetime import date, timezone

            day = date.fromisoformat(facts["posted_date"])
            posted = datetime.combine(day, datetime.min.time(), timezone.utc) - timedelta(hours=14)
            latest = posted + timedelta(hours=50)
            if now < posted:
                return "posting_outside_age_limit"
            if now - posted > timedelta(days=effective["max_job_age_days"]):
                return ("posting_outside_age_limit" if now - latest > timedelta(days=effective["max_job_age_days"])
                        else "posting_age_requires_review")
        else:
            return "posting_timestamp_unknown"
        if not timedelta(0) <= now - posted <= timedelta(days=effective["max_job_age_days"]):
            return "posting_outside_age_limit"
    except (KeyError, TypeError, ValueError):
        return "posting_timestamp_unknown"
    threshold = effective["applicant_limit"]
    if threshold is None:
        return None
    lower, upper = facts.get("applicants_min"), facts.get("applicants_max")
    if ((lower is not None and (type(lower) is not int or lower < 0))
            or (upper is not None and (type(upper) is not int or upper < 0))
            or (lower is not None and upper is not None and lower > upper)):
        return "invalid_applicant_bounds"
    # Counts may be bounded provider labels, not invented exact values.
    if type(lower) is int and lower >= threshold:
        return "applicant_limit_reached"
    if type(upper) is int and 0 <= upper < threshold:
        return None
    if effective["unknown_applicants"] == "allow_lower_bound":
        # Explicit owner acceptance of labels such as 100+. No upper bound is
        # invented; completely missing and threshold-crossing ranges still hold.
        return None if type(lower) is int and upper is None else "applicant_count_requires_review"
    return {"skip": "applicant_count_unknown_skip", "needs_review": "applicant_count_requires_review", "allow": None}[effective["unknown_applicants"]]


async def enqueue(session, platform, url, source, reference=None):
    await store.memory_row(session, lock=True)
    if platform != "naukri" or source not in {"naukri_ui_search", "approved_gmail_alerts", "saved_verified_job"}:
        raise ToolDenied("unsupported_queue_source")
    url = normalized_url(url)
    requisition = url.rsplit("-", 1)[-1]
    identity = str(uuid5(NAMESPACE_URL, platform + ":" + requisition))
    key = PREFIX + identity
    row = await session.get(OwnerPreference, key, populate_existing=True)
    if row:
        return row.value  # Permanent identity survives restarts, slugs and midnight.
    from backend.app.execution.naukri_receipts import prevents_replay

    if await prevents_replay(session, requisition):
        raise ToolDenied("prior_receipt_requires_reconciliation_no_replay")
    from backend.app.models.job import Job

    jobs = (await session.scalars(select(Job).where(
        Job.source_platform == platform,
        (Job.job_url.like("%-" + requisition) | Job.job_url.like("%-" + requisition + "/")),
    ))).all()
    if any([await store.previously_applied(session, job) for job in jobs]):
        raise ToolDenied("prior_application_or_unknown_submission_no_replay")
    config = await configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    if source not in policy.platforms.get(platform, QueuePolicy().platforms["naukri"]).sources:
        raise ToolDenied("queue_source_disabled")
    pending = await session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX), capacity_condition(),
    ))
    if pending >= policy.max_pending:
        raise ToolDenied("queue_backpressure")
    now = await instant(session)
    value = initial_item(config, platform, url, source, reference, now)
    await put(session, key, value)
    await event(session, value, "enqueued")
    return value


def initial_item(config, platform, url, source, reference, now):
    requisition = url.rsplit("-", 1)[-1]
    identity = str(uuid5(NAMESPACE_URL, platform + ":" + requisition))
    return {
        "id": identity, "platform": platform, "requisition": requisition, "url": url,
        "source": source, "source_reference_hash": hashlib.sha256(reference.encode()).hexdigest() if reference else None,
        "stage": "DISCOVERED", "status": "queued", "operation": "inspect_job",
        "revision": 1, "policy_revision": config["revision"], "job_id": None,
        "packet_id": None, "title": None, "company": None, "location": None,
        "facts": {}, "match_score": None, "attempts": 0,
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "available_at": now.isoformat(), "lease_until": None, "lease_token": None,
        "binding": None, "reason": None, "admitted_actions": [],
    }


async def enqueue_batch(session, urls, source):
    """One bounded discovery batch, including permanent replay checks/outbox.

    The native deadline cannot tolerate per-candidate remote transactions/reads.
    The same owner fence and canonical identity apply, with set-based SQL instead
    of weakening replay checks or increasing the transport deadline.
    """
    if source not in {"naukri_ui_search", "saved_verified_job", "approved_gmail_alerts"} or len(urls) > 20:
        raise ToolDenied("bounded_supported_queue_batch_required")
    await store.memory_row(session, lock=True)
    config = await configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    if source not in policy.platforms["naukri"].sources:
        raise ToolDenied("queue_source_disabled")
    normalized = {}
    for raw in urls:
        try:
            url = normalized_url(str(raw))
        except ValueError:
            continue
        normalized.setdefault(url.rsplit("-", 1)[-1], url)
    if not normalized:
        return 0
    identities = {req: str(uuid5(NAMESPACE_URL, "naukri:" + req)) for req in normalized}
    keys = [PREFIX + identity for identity in identities.values()]
    receipt_keys = [prefix + req for req in normalized for prefix in ("naukri_receipt:", "naukri_worker_receipt:")]
    existing = set((await session.scalars(select(OwnerPreference.key).where(
        OwnerPreference.key.in_([*keys, *receipt_keys])
    ))).all())
    from backend.app.models.application_packet import ApplicationPacket
    from backend.app.models.job import Job

    # Match all slug variants for these requisitions. A prior packet under any
    # matching canonical row fences the entire requisition, including unknowns.
    jobs = (await session.scalars(select(Job).where(Job.source_platform == "naukri", or_(
        *(Job.job_url.like("%-" + req + suffix) for req in normalized for suffix in ("", "/"))
    )))).all()
    terminal_packets = set((await session.scalars(select(ApplicationPacket.job_id).where(
        ApplicationPacket.job_id.in_([job.id for job in jobs]),
        ApplicationPacket.lifecycle_state.in_([
            "user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown",
        ]),
    ))).all()) if jobs else set()
    excluded = set()
    for job in jobs:
        applied = (job.id in terminal_packets or job.status in {"applied", "submitted"}
                   or getattr(job, "application_status", None) in {"applied", "submitted", "interview", "offer", "applied_manually", "applied_verified"}
                   or (job.discovery_metadata or {}).get("data_provenance", {}).get("posting_status") == "already_applied")
        if applied:
            # Do not need a valid old slug/host to protect a matching suffix.
            excluded.update(req for req in normalized if job.job_url.rstrip("/").endswith("-" + req))
    pending = await session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX), capacity_condition(),
    ))
    available = max(0, policy.max_pending - pending)
    now = await instant(session)
    values = []
    for req, url in normalized.items():
        if (req in excluded or PREFIX + identities[req] in existing
                or any(prefix + req in existing for prefix in ("naukri_receipt:", "naukri_worker_receipt:"))):
            continue
        if len(values) >= available:
            break
        values.append(initial_item(config, "naukri", url, source, None, now))
    if not values:
        return 0
    from backend.app.services.discovery_budget import insert_for

    inserted = set((await session.scalars(insert_for(session)(OwnerPreference).values([
        {"key": PREFIX + v["id"], "value": v, "created_at": now, "updated_at": now} for v in values
    ]).on_conflict_do_nothing(index_elements=[OwnerPreference.key]).returning(OwnerPreference.key))).all())
    await events_batch(session, [v for v in values if PREFIX + v["id"] in inserted], "enqueued", now)
    return len(inserted)


async def load(session, identity):
    await session.flush()
    row = await session.get(OwnerPreference, PREFIX + str(UUID(str(identity))), populate_existing=True)
    if not row:
        raise ToolDenied("queue_item_not_found")
    return row


async def claim(session, platform, binding, *, operations=None):
    await store.memory_row(session, lock=True)
    current = await configuration(session)
    policy = QueuePolicy.model_validate(current["policy"])
    settings = policy.platforms.get(platform)
    if current["state"] != "RUNNING" or not settings or not settings.enabled or (await store.configuration(session)).mode == "OFF":
        return None
    now = await instant(session)
    # Waiting input/history rows cannot be claimed or have leases recovered.
    # Do not transfer their complete descriptions on every native poll. Keep
    # all leased/executing operations, including expired writes, in this read.
    rows = list((await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX),
        OwnerPreference.value["stage"].as_string().not_in(TERMINAL),
        OwnerPreference.value["platform"].as_string() == platform,
        OwnerPreference.value["status"].as_string().in_(["queued", "leased", "executing"]),
    ).order_by(OwnerPreference.created_at, OwnerPreference.key)
        .execution_options(populate_existing=True))).all())
    for row in rows:
        v = dict(row.value)
        if v["platform"] != platform or v["status"] not in {"leased", "executing"}:
            continue
        if v["lease_until"] and datetime.fromisoformat(v["lease_until"]) <= now:
            uncertain = v["status"] == "executing" and v["operation"] in WRITES
            # An Apply grant not yet admitted can be inspected again; an
            # admitted grant can only be reconciled. Never redeliver its click.
            if v["operation"] == "apply" and not uncertain:
                v["operation"] = "inspect_profile" if v.get("account_sha256") else "inspect_application"
            v.update(stage="SUBMISSION_UNKNOWN" if uncertain else "FAILED_RETRYABLE",
                     status="unknown" if uncertain else "queued", reason="lease_expired",
                     revision=v["revision"] + 1, lease_token=None, lease_until=None)
            row.value = v
            await event(session, v, "lease_expired")
        elif v["lease_until"]:
            return None  # One worker per existing profile, no concurrent writes.
    # Finish existing application/receipt work before opening another listing.
    # Recover every lease first; priority must never bypass an active browser
    # lease or redeliver an expired write. Stable sorting retains FIFO per lane.
    rows.sort(key=lambda row: row.value["operation"] == "inspect_job")
    for row in rows:
        v = dict(row.value)
        if v["platform"] != platform or v["status"] != "queued" or v["stage"] in TERMINAL:
            continue
        if datetime.fromisoformat(v["available_at"]) > now:
            continue
        if v.get("source") and v["source"] not in settings.sources:
            v.update(stage="SKIPPED", status="complete", reason="queue_source_disabled",
                     revision=v["revision"] + 1, updated_at=now.isoformat())
            row.value = v
            await event(session, v, "source_scope_revoked")
            continue
        if operations is not None and v["operation"] not in operations:
            continue
        if v["operation"] in WRITES and (not settings.owner_submission_authorized or settings.mode == "PREPARE_ONLY"):
            continue
        v.update(status="leased", revision=v["revision"] + 1,
                 policy_revision=current["revision"], binding=binding,
                 lease_token=str(uuid4()), lease_until=(now + timedelta(seconds=180)).isoformat(),
                 attempts=v["attempts"] + 1, updated_at=now.isoformat())
        row.value = v
        await event(session, v, "claimed")
        return v
    return None


async def leased(session, identity, revision, token, binding):
    await store.memory_row(session, lock=True)
    row = await load(session, identity)
    v, current, now = row.value, await configuration(session), await instant(session)
    if (current["state"] != "RUNNING" or v["policy_revision"] != current["revision"]
            or v["revision"] != revision or v["lease_token"] != str(token)
            or v["binding"] != binding or v["status"] not in {"leased", "executing"}
            or not v["lease_until"] or datetime.fromisoformat(v["lease_until"]) <= now):
        raise ToolDenied("queue_lease_lost")
    return row


def eligibility_hold(value, reason):
    """Keep rejected discovery/preparation out of the application worker lane."""
    excluded = reason in {
        "posting_outside_age_limit", "applicant_limit_reached", "applicant_count_unknown_skip",
        "prior_application_or_unknown_submission_no_replay", "required_experience_outside_verified_band",
        "current_profile_preferences_or_required_skills_exclude_job", "minimum_match_score_required",
        "advertised_experience_outside_platform_preferences", "advertised_salary_outside_platform_preferences",
        "vacancy_closed_expired_or_invalid",
    }
    value.update(stage="SKIPPED" if excluded else "NEEDS_INPUT",
                 status="complete" if excluded else "waiting", reason=reason)


async def eligible_context(session, value, policy, job):
    from backend.app.execution.recurring import context

    profile, confirmed, _ = await context(session)
    if not confirmed or (value.get("profile_version") is not None and profile.version != value["profile_version"]):
        raise ToolDenied("verified_profile_context_changed")
    from backend.app.models.company import Company

    company = await session.get(Company, job.company_id) if job.company_id else None
    check_eligibility(value, policy, job, company, profile, await instant(session))
    return profile


def check_eligibility(value, policy, job, company, profile, now):
    """Same eligibility decisions for fresh preparation and retained-fact review.

    Retained facts may reject or schedule a fresh read; they never authorize a
    browser action or turn a stale observation into an application grant.
    """
    from backend.app.execution.naukri import reviewed_job_context
    from backend.app.schemas.candidate_profile import CandidateProfileRead
    from backend.app.services.applications.platforms.naukri import posting_unavailable
    from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher

    if posting_unavailable(job):
        raise ToolDenied("vacancy_closed_expired_or_invalid")
    job_view, company = reviewed_job_context(job, company)
    candidate = CandidateProfileRead.model_validate(profile)
    custom = policy.platforms[value["platform"]]
    if custom.preferences_mode == "custom":
        p = custom.preferences
        candidate = candidate.model_copy(update={"preferences": candidate.preferences.model_copy(update={
            "target_titles": p.roles, "preferred_locations": p.locations,
            "minimum_salary": p.minimum_salary, "salary_currency": p.salary_currency,
            "salary_period": p.salary_period,
            "excluded_companies": list(dict.fromkeys([*candidate.preferences.excluded_companies, *p.excluded_companies])),
        })})
        metadata = job.discovery_metadata or {}
        lower, upper = metadata.get("experience_min_years"), metadata.get("experience_max_years")
        if ((p.experience_min is not None and (lower is None or lower < p.experience_min))
                or (p.experience_max is not None and (upper is None or upper > p.experience_max))):
            raise ToolDenied("advertised_experience_outside_platform_preferences")
        if p.maximum_salary is not None:
            if (job_view.salary_min is None or job_view.salary_max is None
                    or job_view.salary_currency != p.salary_currency or job_view.salary_period != p.salary_period):
                raise ToolDenied("salary_comparison_requires_review")
            if job_view.salary_max > p.maximum_salary:
                raise ToolDenied("advertised_salary_outside_platform_preferences")
    metadata = job.discovery_metadata or {}
    lower, upper = metadata.get("experience_min_years"), metadata.get("experience_max_years")
    years = profile.verified_experience_years
    if lower is None or upper is None or years is None:
        raise ToolDenied("verified_experience_requirements_required")
    if not lower <= years <= upper:
        raise ToolDenied("required_experience_outside_verified_band")
    match = JobDiscoveryMatcher(None).match(job_view, candidate, company)
    effective = limits(policy, value["platform"])
    reason = listing_exclusion(value["facts"], effective, now)
    if reason:
        raise ToolDenied(reason)
    value["match_score"] = match.match_score
    if match.exclusion_reasons or match.negative_factors or match.missing_skills:
        raise ToolDenied("current_profile_preferences_or_required_skills_exclude_job")
    if match.match_score < effective["minimum_match_score"]:
        raise ToolDenied("minimum_match_score_required")
    allowed_unknowns = {"company_size", "salary", "experience_suitability"}
    if candidate.preferences.remote_preference in {None, "any"}:
        allowed_unknowns.add("remote_policy")
    if value["facts"].get("posted_date") and not reason:
        # The precision-aware freshness check above establishes the configured
        # age bound without inventing an exact timestamp for the matcher.
        allowed_unknowns.add("publication_date")
    if set(match.unknown_fields) - allowed_unknowns:
        raise ToolDenied("uncertain_job_requirements_require_review")
    return profile


async def write_context(session, value, policy, settings):
    """A queued action or owner grant alone cannot make a vacancy eligible."""
    from backend.app.execution.naukri_identity import check_work
    from backend.app.execution.naukri_upload import preflight
    from backend.app.models.job import Job
    from backend.app.services.applications.service import ApplicationPacketService

    if not value.get("job_id") or not value.get("packet_id"):
        raise ToolDenied("prepared_application_required")
    await check_work(session, value)
    job = await session.get(Job, UUID(value["job_id"]), populate_existing=True)
    if not job or await store.previously_applied(session, job):
        raise ToolDenied("prior_application_or_unknown_submission_no_replay")
    if job.source_platform != value["platform"] or normalized_url(job.job_url).rsplit("-", 1)[-1] != value["requisition"]:
        raise ToolDenied("queue_job_identity_changed")
    await eligible_context(session, value, policy, job)
    try:
        checked = datetime.fromisoformat(value["facts"]["prior_status_checked_at"])
        if (checked.tzinfo is None or not timedelta(0) <= (await instant(session)) - checked <= timedelta(minutes=2)
                or value["facts"].get("prior_status") != "NOT_APPLIED"):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ToolDenied("fresh_provider_application_status_required") from None
    packet = await ApplicationPacketService(session).read(UUID(value["packet_id"]))
    if str(packet.job_id) != value["job_id"]:
        raise ToolDenied("queue_packet_job_mismatch")
    if packet.revision != value.get("packet_revision") or packet.readiness.stale:
        raise ToolDenied("queue_packet_context_changed")
    checked_pdf = await preflight(session, packet, settings)
    if checked_pdf["state"] != "PDF_VERIFIED_LOCAL":
        raise ToolDenied(checked_pdf["reason"])
    from backend.app.execution.naukri_submission import account_current

    now = await instant(session)
    if not account_current(value, now):
        raise ToolDenied("fresh_provider_account_observation_required")
    # Direct Apply may submit the resume already saved on Naukri immediately.
    # A locally verified file alone is not proof of that provider-side file.
    try:
        checked_at = datetime.fromisoformat(value["facts"]["provider_resume_checked_at"])
        if (checked_at.tzinfo is None
                or not timedelta(0) <= now - checked_at <= timedelta(minutes=2)
                or value["facts"].get("provider_resume_sha256") != checked_pdf["sha256"]
                or value["facts"].get("provider_resume_source") != "profile_download_ui"):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ToolDenied("fresh_provider_resume_binding_required") from None
    return packet, checked_pdf


async def admit(session, identity, revision, token, binding, settings=None):
    row = await leased(session, identity, revision, token, binding)
    if (await store.configuration(session)).mode == "OFF":
        raise ToolDenied("execution_mode_off")
    v = dict(row.value)
    if v["status"] != "leased":
        raise ToolDenied("queue_action_already_admitted")
    config = await configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    setting = policy.platforms[v["platform"]]
    from backend.app.local_agent.policies import get_policy

    local_policy = await get_policy(session)
    if local_policy["platforms"].get(v["platform"], local_policy["default"]) == "disabled":
        raise ToolDenied("platform_disabled")
    if not setting.enabled:
        raise ToolDenied("platform_disabled")
    if v["operation"] in WRITES:
        if local_policy["platforms"].get(v["platform"], local_policy["default"]) in {"manual_only", "draft_only"}:
            raise ToolDenied("platform_policy_requires_manual_review")
        if not setting.owner_submission_authorized or setting.mode == "PREPARE_ONLY":
            raise ToolDenied("standing_submission_scope_required")
        if setting.mode == "AUTOMATIC":
            from backend.app.execution.naukri_automatic import require_first_receipt

            await require_first_receipt(session)
        from backend.app.execution.naukri_receipts import prevents_replay

        if await prevents_replay(session, v["requisition"]):
            raise ToolDenied("prior_receipt_requires_reconciliation_no_replay")
        fingerprint = f"{v['operation']}:{v.get('step_fingerprint', 'initial')}"
        if any(a["fingerprint"] == fingerprint for a in v["admitted_actions"]):
            raise ToolDenied("queue_action_replay_forbidden")
        if v["operation"] == "apply" and any(a["fingerprint"].startswith("apply:") for a in v["admitted_actions"]):
            raise ToolDenied("queue_apply_replay_forbidden")
        if settings is None:
            from backend.app.core.config import get_settings

            settings = get_settings()
        if v["operation"] == "answer_questionnaire":
            from backend.app.execution.naukri_questionnaires import context

            await context(session, v, settings, writing=True)
            if v.get("step_fingerprint") != v["questionnaire"]["step_sha256"] or not v.get("questionnaire_answer"):
                raise ToolDenied("questionnaire_reviewed_step_required")
        else:
            await write_context(session, v, policy, settings)
        if setting.mode == "SUPERVISED" and v["operation"] == "apply":
            # The initial one-application authorization does not renew at
            # midnight. Uncertain attempts consume it until explicitly reviewed.
            trials = [r.value for r in await items(session) if r.value["platform"] == v["platform"]]
            attempted = sum(any(a["fingerprint"].startswith("apply:") for a in x.get("admitted_actions", [])) for x in trials)
            if attempted >= setting.supervised_submission_cap:
                raise ToolDenied("supervised_application_allowance_exhausted")
        # Budget admission is persistent and conservative: uncertain submissions
        # consume a reservation and are never refunded automatically.
        day = (await instant(session)).astimezone(ZoneInfo(policy.day_timezone)).date().isoformat()
        budget_key = "apply_budget:" + v["platform"] + ":" + day
        budget = await session.get(OwnerPreference, budget_key, populate_existing=True)
        used = dict(budget.value) if budget else {"reservations": []}
        cap = limits(policy, v["platform"])["daily_cap"]
        if setting.mode == "SUPERVISED":
            cap = min(cap, setting.supervised_submission_cap)
        if v["id"] not in used["reservations"]:
            if len(used["reservations"]) >= cap:
                raise ToolDenied("daily_application_cap_reached")
            now = await instant(session)
            # Admission timestamps survive midnight and process restarts. Every
            # uncertain application keeps its reservation; no automatic refund.
            recent = [r.value for r in await items(session) if r.value["platform"] == v["platform"]]
            hourly = sum(any(
                now - timedelta(hours=1) <= datetime.fromisoformat(a["at"]) <= now
                for a in x.get("admitted_actions", [])
            ) for x in recent)
            if hourly >= setting.hourly_submission_cap:
                raise ToolDenied("hourly_application_cap_reached")
            used["reservations"] = [*used["reservations"], v["id"]]
            await put(session, budget_key, used)
        v["admitted_actions"] = [*v["admitted_actions"], {
            "id": str(uuid4()), "fingerprint": fingerprint,
            "at": (await instant(session)).isoformat(),
        }]
        if v["operation"] == "answer_questionnaire":
            v["questionnaire_answers"] = [*v.get("questionnaire_answers", []), {
                "step": dict(v["questionnaire"]), "answer": dict(v["questionnaire_answer"]),
                "packet_revision": v["packet_revision"], "profile_version": v["profile_version"],
                "admitted_at": (await instant(session)).isoformat(), "state": "admitted_not_a_receipt",
            }]
        if v["operation"] == "apply":
            from backend.app.models.application_packet import (
                ApplicationEvent,
                ApplicationPacket,
            )

            packet = await session.get(ApplicationPacket, UUID(v["packet_id"]), populate_existing=True)
            previous_state = packet.lifecycle_state
            packet.lifecycle_state = "submitting"
            packet.revision += 1
            packet.approved_revision = None
            v["packet_revision"] = packet.revision
            session.add(ApplicationEvent(packet_id=packet.id, packet_revision=packet.revision,
                                         event_type="naukri_apply_admitted", previous_state=previous_state,
                                         next_state="submitting", origin="local_worker"))
            # The same canonical packet fences every legacy/manual channel
            # before the external click, including a lost admission response.
    v.update(status="executing", revision=v["revision"] + 1)
    row.value = v
    await event(session, v, "admitted")
    return v


def public(value):
    return {key: value.get(key) for key in (
        "id", "platform", "requisition", "url", "stage", "status", "operation",
        "revision", "job_id", "packet_id", "title", "company", "location",
        "match_score", "attempts", "reason", "created_at", "updated_at",
        "submission_mode", "receipt_source",
    )} | {"posted_at": value.get("facts", {}).get("posted_at"),
         "posted_date": value.get("facts", {}).get("posted_date"),
         "applicants_min": value.get("facts", {}).get("applicants_min"),
         "applicants_max": value.get("facts", {}).get("applicants_max")}


async def listing(session, *, platform=None, stage=None, search=None, location=None, minimum_score=None, limit=100, offset=0):
    query = select(OwnerPreference).where(OwnerPreference.key.startswith(PREFIX))
    if platform:
        query = query.where(OwnerPreference.value["platform"].as_string() == platform)
    if stage:
        query = query.where(OwnerPreference.value["stage"].as_string() == stage)
    if search:
        from sqlalchemy import or_

        query = query.where(or_(*(OwnerPreference.value[key].as_string().ilike("%" + search + "%")
                                  for key in ("title", "company", "requisition", "location"))))
    if location:
        query = query.where(OwnerPreference.value["location"].as_string().ilike("%" + location + "%"))
    if minimum_score is not None:
        query = query.where(OwnerPreference.value["match_score"].as_float() >= minimum_score)
    rows = (await session.scalars(query.order_by(
        OwnerPreference.created_at.desc(), OwnerPreference.key
    ).offset(offset).limit(limit))).all()
    stage_expression = OwnerPreference.value["stage"].as_string().label("queue_stage")
    counts = (await session.execute(select(
        stage_expression, func.count(), func.sum(case((query.whereclause, 1), else_=0))
    ).where(OwnerPreference.key.startswith(PREFIX)).group_by(
        "queue_stage"
    ))).all()
    total = sum(count[2] for count in counts)
    preferences = dict((await session.execute(select(OwnerPreference.key, OwnerPreference.value).where(
        OwnerPreference.key.in_([POLICY_KEY, "apply_search:naukri", "apply_consumer:naukri"])
    ))).all())
    discovery = preferences.get("apply_search:naukri")
    consumer = {k: discovery.get(k) for k in ("last_started_at", "last_finished_at", "next_at", "last_cycle_count", "last_error")} if discovery else None
    heartbeat = preferences.get("apply_consumer:naukri")
    worker = {k: heartbeat.get(k) for k in ("last_poll_at", "busy", "capability")} if heartbeat else None
    config = preferences.get(POLICY_KEY, {
        "revision": 0, "state": "STOPPED", "policy": QueuePolicy().model_dump(mode="json")
    })
    policy = QueuePolicy.model_validate(config["policy"])
    day = (await instant(session)).astimezone(ZoneInfo(policy.day_timezone)).date().isoformat()
    budget = await session.get(OwnerPreference, "apply_budget:naukri:" + day, populate_existing=True)
    used = len(budget.value.get("reservations", [])) if budget else 0
    cap = limits(policy, "naukri")["daily_cap"]
    if policy.platforms["naukri"].mode == "SUPERVISED":
        cap = min(cap, policy.platforms["naukri"].supervised_submission_cap)
    return {"items": [public(r.value) for r in rows], "total": total,
            "counts": {stage: count for stage, count, _ in counts}, "limit": limit, "offset": offset,
            "configuration": config, "discovery": consumer, "consumer": worker,
            "quota": {"reserved_today": used, "daily_cap": cap, "remaining": max(0, cap - used),
                      "hourly_cap": policy.platforms["naukri"].hourly_submission_cap},
            "capabilities": {"background_read": "implemented_not_live_accepted", "submission": "direct_apply_candidate_not_live_accepted",
                             "locked_screen": "NOT_TESTED", "queue": "existing_postgresql"}}


async def index_retained_receipts(session):
    """Index existing genuine observations for history; create no new attempt.

    The original receipt bytes and packet lifecycle are preserved. In particular,
    owner-authorized UI evidence never becomes installed-worker evidence.
    """
    from backend.app.execution.naukri_receipts import PREFIX as RECEIPT_PREFIX
    from backend.app.execution.naukri_receipts import recorded_application

    async def pending():
        cursor = await session.get(OwnerPreference, "apply_history_cursor", populate_existing=True)
        query = select(OwnerPreference).where(OwnerPreference.key.startswith(RECEIPT_PREFIX))
        if cursor:
            from sqlalchemy import and_, or_

            timestamp = datetime.fromisoformat(cursor.value["updated_at"])
            query = query.where(or_(
                OwnerPreference.updated_at > timestamp,
                and_(OwnerPreference.updated_at == timestamp, OwnerPreference.key > cursor.value["key"]),
            ))
        return list((await session.scalars(query.order_by(
            OwnerPreference.updated_at, OwnerPreference.key
        ).limit(5).execution_options(populate_existing=True))).all())

    records = await pending()
    if not records:
        return 0
    await store.memory_row(session, lock=True)
    records = await pending()
    if not records:
        return 0
    now = await instant(session)
    added = 0
    for receipt in records:
        source = receipt.value
        if not recorded_application(receipt.key, source, now):
            continue
        identity = str(uuid5(NAMESPACE_URL, "naukri:" + source["requisition"]))
        row = await session.get(OwnerPreference, PREFIX + identity, populate_existing=True)
        if row and row.value["stage"] == "SUBMITTED_RECORDED":
            continue
        value = dict(row.value) if row else {
            "id": identity, "platform": "naukri", "requisition": source["requisition"],
            "url": None, "job_id": None, "packet_id": None,
            "source": "retained_receipt", "facts": {}, "location": None,
            "match_score": None, "attempts": 0, "revision": 0,
            "created_at": source["observed_at"], "admitted_actions": [],
        }
        value.update(
            stage="SUBMITTED_RECORDED", status="complete", operation=None,
            title=source.get("job_title"), company=source.get("hiring_company"),
            reason="retained_provider_ui_observation", revision=value["revision"] + 1,
            updated_at=now.isoformat(), lease_until=None, lease_token=None, binding=None,
            submission_mode=source["operation_mode"], receipt_source=source["confirmation_source"],
        )
        await put(session, PREFIX + identity, value)
        await event(session, value, "retained_receipt_indexed")
        added += 1
    await put(session, "apply_history_cursor", {
        "updated_at": records[-1].updated_at.isoformat(), "key": records[-1].key,
    })
    return added
