"""Durable application messages using the existing private PostgreSQL store.

One owner fence serializes claims, budget admission and revocation. No broker,
new pool, DDL, portal transport or implicit submission grant is introduced.
"""

import hashlib
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.naukri import normalized_url
from backend.app.execution.queue_contracts import QueuePolicy

POLICY_KEY = "application_queue_policy"
PREFIX = "apply_work:"
EVENT = "apply_event:"
TERMINAL = {"SUBMITTED_RECORDED", "FAILED_FINAL", "SKIPPED"}
WRITES = {"apply", "answer", "upload_resume"}


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


async def fence(session, reason):
    search = await session.get(OwnerPreference, "apply_search:naukri", populate_existing=True)
    if search:
        search.value = {**search.value, "status": "idle", "lease_token": None, "lease_until": None,
                        "next_at": None, "revision": search.value["revision"] + 1, "last_error": reason}
    for row in await items(session, active_only=True):
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
        await event(session, value, "fenced")


async def configure(session, data):
    await store.memory_row(session, lock=True)
    current = await configuration(session)
    if current["revision"] != data.expected_revision:
        raise ToolDenied("queue_policy_revision_conflict")
    await fence(session, "queue_policy_changed")
    value = {**current, "revision": current["revision"] + 1,
             "state": "PAUSED" if current["state"] == "RUNNING" else current["state"],
             "policy": data.policy.model_dump(mode="json")}
    await put(session, POLICY_KEY, value)
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
        state = "RUNNING"
        for row in await items(session, active_only=True):
            v = dict(row.value)
            if v["stage"] == "PAUSED" and v["reason"] in {"owner_pause", "global_stop", "queue_policy_changed"}:
                previous = v.get("paused_context", {})
                waiting = previous.get("status") == "waiting"
                v.update(stage=previous.get("stage", "DISCOVERED"),
                         status="waiting" if waiting else "queued",
                         operation=previous.get("operation", "inspect_job"),
                         reason=previous.get("reason"), revision=v["revision"] + 1)
                if not waiting and v["operation"] in WRITES:
                    v.update(operation="inspect_application", stage="VERIFYING")
                row.value = v
                await event(session, v, "resumed_for_fresh_inspection")
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
        posted = datetime.fromisoformat(facts["posted_at"])
        if posted.tzinfo is None or not timedelta(0) <= now - posted <= timedelta(days=effective["max_job_age_days"]):
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
        OwnerPreference.key.startswith(PREFIX),
        OwnerPreference.value["stage"].as_string().not_in(TERMINAL),
    ))
    if pending >= policy.max_pending:
        raise ToolDenied("queue_backpressure")
    now = await instant(session)
    value = {
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
    await put(session, key, value)
    await event(session, value, "enqueued")
    return value


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
    rows = await items(session, active_only=True)
    for row in rows:
        v = dict(row.value)
        if v["platform"] != platform or v["status"] not in {"leased", "executing"}:
            continue
        if v["lease_until"] and datetime.fromisoformat(v["lease_until"]) <= now:
            uncertain = v["status"] == "executing" and v["operation"] in WRITES
            v.update(stage="SUBMISSION_UNKNOWN" if uncertain else "FAILED_RETRYABLE",
                     status="unknown" if uncertain else "queued", reason="lease_expired",
                     revision=v["revision"] + 1, lease_token=None, lease_until=None)
            row.value = v
            await event(session, v, "lease_expired")
        elif v["lease_until"]:
            return None  # One worker per existing profile, no concurrent writes.
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


async def eligible_context(session, value, policy, job):
    from backend.app.execution.recurring import context

    profile, confirmed, _ = await context(session)
    if not confirmed or (value.get("profile_version") is not None and profile.version != value["profile_version"]):
        raise ToolDenied("verified_profile_context_changed")
    from backend.app.execution.naukri import reviewed_job_context
    from backend.app.models.company import Company
    from backend.app.schemas.candidate_profile import CandidateProfileRead
    from backend.app.services.applications.platforms.naukri import posting_unavailable
    from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher

    if posting_unavailable(job):
        raise ToolDenied("vacancy_closed_expired_or_invalid")
    company = await session.get(Company, job.company_id) if job.company_id else None
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
    match = JobDiscoveryMatcher(session).match(job_view, candidate, company)
    effective = limits(policy, value["platform"])
    reason = listing_exclusion(value["facts"], effective, await instant(session))
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
    if set(match.unknown_fields) - allowed_unknowns:
        raise ToolDenied("uncertain_job_requirements_require_review")
    return profile


async def write_context(session, value, policy, settings):
    """A queued action or owner grant alone cannot make a vacancy eligible."""
    from backend.app.execution.naukri_upload import preflight
    from backend.app.models.job import Job
    from backend.app.services.applications.service import ApplicationPacketService

    if not value.get("job_id") or not value.get("packet_id"):
        raise ToolDenied("prepared_application_required")
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
    # Direct Apply may submit the resume already saved on Naukri immediately.
    # A locally verified file alone is not proof of that provider-side file.
    try:
        checked_at = datetime.fromisoformat(value["facts"]["provider_resume_checked_at"])
        if (checked_at.tzinfo is None
                or not timedelta(0) <= (await instant(session)) - checked_at <= timedelta(minutes=2)
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
        if not setting.owner_submission_authorized or setting.mode == "PREPARE_ONLY":
            raise ToolDenied("standing_submission_scope_required")
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
        await write_context(session, v, policy, settings)
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
            used["reservations"] = [*used["reservations"], v["id"]]
            await put(session, budget_key, used)
        v["admitted_actions"] = [*v["admitted_actions"], {
            "id": str(uuid4()), "fingerprint": fingerprint,
            "at": (await instant(session)).isoformat(),
        }]
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
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.order_by(
        OwnerPreference.created_at.desc(), OwnerPreference.key
    ).offset(offset).limit(limit))).all()
    stage_expression = OwnerPreference.value["stage"].as_string().label("queue_stage")
    counts = (await session.execute(select(
        stage_expression, func.count()
    ).where(OwnerPreference.key.startswith(PREFIX)).group_by(
        "queue_stage"
    ))).all()
    discovery = await session.get(OwnerPreference, "apply_search:naukri", populate_existing=True)
    consumer = {k: discovery.value.get(k) for k in ("last_started_at", "last_finished_at", "next_at", "last_cycle_count", "last_error")} if discovery else None
    heartbeat = await session.get(OwnerPreference, "apply_consumer:naukri", populate_existing=True)
    worker = {k: heartbeat.value.get(k) for k in ("last_poll_at", "busy", "capability")} if heartbeat else None
    return {"items": [public(r.value) for r in rows], "total": total,
            "counts": dict(counts), "limit": limit, "offset": offset,
            "configuration": await configuration(session), "discovery": consumer, "consumer": worker,
            "capabilities": {"background_read": "implemented_not_live_accepted", "submission": "executor_pending",
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
