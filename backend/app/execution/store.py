"""Execution intent and outbox share the existing private PostgreSQL store.

No new live DDL. All mutators take the owner lock before execution rows; unique
identity keys prevent concurrent/new-command duplicate intents. Workers must
commit claims before work, and recheck fence/lease before each side effect.
"""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from backend.app.agent.store import memory_row as owner_lock
from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution.contracts import Configuration
from backend.app.execution.naukri import normalized_url
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job

PREFIX = "exec:"
TERMINAL = {"REJECTED", "FAILED_FINAL", "SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN"}
TRANSITIONS = {
    "DISCOVERED": {"MATCHED"},
    "MATCHED": {"ELIGIBLE", "REJECTED", "NEEDS_INPUT"},
    "ELIGIBLE": {"PREPARING"},
    "PREPARING": {"FILLING", "NEEDS_INPUT", "READY_FOR_REVIEW"},
    "FILLING": {"NEEDS_INPUT", "READY_FOR_REVIEW"},
    "NEEDS_INPUT": {"PREPARING"},
    "READY_FOR_REVIEW": {"FILLING", "SUBMITTING", "NEEDS_INPUT"},
    "SUBMITTING": {"SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN"},
    "FAILED_RETRYABLE": {"PREPARING", "FAILED_FINAL"},
}


async def memory_row(session, *, lock=False):
    # Factories disable autoflush; refresh must not discard pending transitions.
    await session.flush()
    return await owner_lock(session, lock=lock)


async def configuration(session):
    row = await session.get(OwnerPreference, "exec_config:naukri")
    return Configuration.model_validate(row.value if row else {})


async def configure(session, config):
    await memory_row(session, lock=True)
    if (
        config.submission_permission
        or config.destinations
        or config.mode == "AUTO_APPLY_WHEN_AUTHORIZED"
    ):
        raise ToolDenied("naukri_submission_capability_not_verified")
    row = await session.get(OwnerPreference, "exec_config:naukri")
    if row:
        row.value = config.model_dump(mode="json")
    else:
        session.add(
            OwnerPreference(
                key="exec_config:naukri", value=config.model_dump(mode="json")
            )
        )
    if config.mode == "OFF":
        for r in await rows(session):
            if r.value["state"] not in TERMINAL | {"PAUSED"}:
                await control(session, r.value["id"], "pause", r.value["revision"])


async def rows(session):
    return list(
        (
            await session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.startswith(PREFIX))
                .order_by(OwnerPreference.created_at, OwnerPreference.key)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def load(session, execution_id):
    await session.flush()
    row = await session.get(
        OwnerPreference, PREFIX + str(UUID(str(execution_id))), populate_existing=True
    )
    if row is None:
        raise ToolDenied("execution_not_found")
    return row


async def emit(session, value, event, now):
    identity = str(uuid5(NAMESPACE_URL, f"{value['id']}:{value['revision']}:{event}"))
    session.add(
        OwnerPreference(
            key="exec_event:" + identity,
            value={
                "id": identity,
                "execution_id": value["id"],
                "event": event,
                "state": value["state"],
                "at": now.isoformat(),
                "delivered": False,
            },
        )
    )


async def move(session, row, state, reason=None):
    value = dict(row.value)
    if state in {"SUBMITTING", "SUBMITTED_CONFIRMED"} and value["platform"] == "naukri":
        raise ToolDenied("naukri_submission_capability_not_verified")
    current = value["state"]
    if state not in TRANSITIONS.get(current, set()):
        raise ToolDenied("invalid_execution_transition")
    value.update(state=state, revision=value["revision"] + 1, diagnostic=reason)
    value["history"] = [
        *value["history"],
        {"from": current, "to": state, "reason": reason},
    ]
    row.value = value
    await emit(session, value, "state_changed", await instant(session))
    return value


async def start(session, job_ids):
    await memory_row(session, lock=True)
    if (await configuration(session)).mode == "OFF":
        raise ToolDenied("execution_mode_off")
    now, result = await instant(session), []
    for job_id in dict.fromkeys(job_ids):
        job = await session.get(Job, job_id)
        if not job or job.source_platform != "naukri":
            raise ToolDenied("saved_naukri_job_required")
        url = normalized_url(job.job_url)
        employer = (
            await session.get(Company, job.company_id) if job.company_id else None
        )
        identity = str(uuid5(NAMESPACE_URL, "naukri:" + url.rsplit("-", 1)[-1]))
        row = await session.get(OwnerPreference, PREFIX + identity)
        if row is None:
            # Existing application evidence is checked again by the worker.
            value = {
                "id": identity,
                "attempt_id": str(uuid4()),
                "job_id": str(job.id),
                "platform": "naukri",
                "role": job.title,
                "employer": employer.name if employer else None,
                "normalized_url": url,
                "requisition_id": url.rsplit("-", 1)[-1],
                "employer_id": str(job.company_id) if job.company_id else None,
                "state": "DISCOVERED",
                "revision": 1,
                "history": [],
                "evidence": [],
                "profile_version": None,
                "approved_answer_revisions": {},
                "packet_id": None,
                "fence": 0,
                "attempts": 0,
                "cancelled": False,
                "lease_until": None,
                "available_at": now.isoformat(),
                "heartbeat_at": None,
                "diagnostic": None,
                "created_at": now.isoformat(),
            }
            row = OwnerPreference(key=PREFIX + identity, value=value)
            session.add(row)
            await emit(session, value, "intent_created", now)
            await session.flush()
        result.append(row.value)
    return result


async def control(session, execution_id, action, revision):
    await memory_row(session, lock=True)
    row = await load(session, execution_id)
    v = dict(row.value)
    if v["revision"] != revision:
        raise ToolDenied("execution_revision_conflict")
    if v["state"] in TERMINAL:
        raise ToolDenied("execution_terminal_check_history")
    if action == "resume":
        if (
            v["state"] not in {"PAUSED", "NEEDS_INPUT"}
            or (await configuration(session)).mode == "OFF"
        ):
            raise ToolDenied("execution_not_resumable")
        state = (
            v["paused_state"]
            if v["state"] == "PAUSED"
            else "PREPARING"
            if v["packet_id"]
            else "DISCOVERED"
        )
        v["attempts"] = 0
    else:
        state = (
            "SUBMISSION_UNKNOWN"
            if v["state"] == "SUBMITTING"
            else "FAILED_FINAL"
            if action == "cancel"
            else "PAUSED"
        )
        v["paused_state"] = v["state"]
        v["cancelled"] = action == "cancel"
    # A worker holding an old fence cannot advance after any owner control.
    v.update(
        state=state, revision=v["revision"] + 1, fence=v["fence"] + 1, lease_until=None
    )
    row.value = v
    await emit(session, v, "owner_" + action, await instant(session))
    return v


async def claim(session):
    await memory_row(session, lock=True)
    if (await configuration(session)).mode == "OFF":
        return None
    now = await instant(session)
    for row in await rows(session):
        v = dict(row.value)
        if v["state"] in TERMINAL | {
            "PAUSED",
            "NEEDS_INPUT",
            "READY_FOR_REVIEW",
            "FILLING",
        }:
            continue
        if v["lease_until"] and datetime.fromisoformat(v["lease_until"]) > now:
            continue
        if v["state"] == "SUBMITTING":
            await move(
                session, row, "SUBMISSION_UNKNOWN", "dispatch_outcome_unknown_no_replay"
            )
            continue
        if datetime.fromisoformat(v["available_at"]) > now:
            continue
        if v["attempts"] >= 3:
            v.update(
                state="FAILED_FINAL",
                diagnostic="retry_limit",
                revision=v["revision"] + 1,
            )
            row.value = v
            await emit(session, v, "retry_limit", now)
            continue
        v.update(
            fence=v["fence"] + 1,
            attempts=v["attempts"] + 1,
            lease_until=(now + timedelta(seconds=90)).isoformat(),
            heartbeat_at=now.isoformat(),
        )
        row.value = v
        return v["id"], v["fence"]
    return None


async def fenced(session, identity):
    await memory_row(session, lock=True)
    row = await load(session, identity[0])
    v, now = row.value, await instant(session)
    if (
        v["fence"] != identity[1]
        or not v["lease_until"]
        or datetime.fromisoformat(v["lease_until"]) <= now
        or v["state"] in TERMINAL | {"PAUSED"}
    ):
        raise ToolDenied("execution_lease_lost")
    return row


async def heartbeat(session, identity):
    row = await fenced(session, identity)
    now = await instant(session)
    row.value = {
        **row.value,
        "heartbeat_at": now.isoformat(),
        "lease_until": (now + timedelta(seconds=90)).isoformat(),
    }


async def previously_applied(session, job):
    if getattr(job, "application_status", None) in {
        "applied",
        "submitted",
        "interview",
        "offer",
        "applied_manually",
        "applied_verified",
    } or job.status in {"applied", "submitted"}:
        return True
    terminal = [
        "user_reported_submitted",
        "provider_confirmed_submitted",
        "submitting",
        "submission_unknown",
    ]
    if await session.scalar(
        select(ApplicationPacket.id).where(
            ApplicationPacket.job_id == job.id,
            ApplicationPacket.lifecycle_state.in_(terminal),
        )
    ):
        return True
    prior_urls = (
        await session.scalars(
            select(Job.job_url)
            .join(ApplicationPacket, ApplicationPacket.job_id == Job.id)
            .where(
                Job.source_platform == "naukri",
                ApplicationPacket.lifecycle_state.in_(terminal),
            )
        )
    ).all()
    requisition = normalized_url(job.job_url).rsplit("-", 1)[-1]
    for url in prior_urls:
        try:
            if normalized_url(url).rsplit("-", 1)[-1] == requisition:
                return True
        except ValueError:
            continue
    return False


async def events(session):
    """Stable event IDs permit consumer deduplication across at-least-once pulls."""
    return [
        r.value
        for r in (
            await session.scalars(
                select(OwnerPreference)
                .where(
                    OwnerPreference.key.startswith("exec_event:"),
                    OwnerPreference.value["delivered"].as_boolean().is_(False),
                )
                .order_by(OwnerPreference.created_at, OwnerPreference.key)
                .limit(100)
            )
        ).all()
    ]


async def acknowledge(session, event_id):
    await memory_row(session, lock=True)
    row = await session.get(OwnerPreference, "exec_event:" + str(event_id))
    if row is None:
        raise ToolDenied("execution_event_not_found")
    row.value = {**row.value, "delivered": True}


async def lock_packet_execution(session, packet_id):
    from backend.app.knowledge.missing_input import storage_available

    if not await storage_available(session):
        return None
    await session.flush()
    row = await session.scalar(
        select(OwnerPreference).where(
            OwnerPreference.key.startswith(PREFIX),
            OwnerPreference.value["packet_id"].as_string() == str(packet_id),
        )
    )
    if row is not None:
        await memory_row(session, lock=True)
        row = await load(session, row.value["id"])
    return row


async def lock_plan_execution(session, plan_id):
    plan = await session.get(OwnerPreference, "fill_plan:" + str(plan_id))
    return (
        await lock_packet_execution(session, plan.value["application_id"])
        if plan
        else None
    )


async def fill_event(session, row, plan, status):
    if row is None:
        return
    value = row.value
    if value["state"] in TERMINAL | {"PAUSED"} or value["cancelled"]:
        if status == "fill_authorized":
            raise ToolDenied("execution_paused_or_cancelled")
        return
    next_state = (
        "FILLING"
        if status == "fill_authorized"
        else "READY_FOR_REVIEW"
        if status == "form_filled"
        else "NEEDS_INPUT"
    )
    if next_state != value["state"]:
        if next_state not in TRANSITIONS.get(value["state"], set()):
            raise ToolDenied("execution_not_ready_for_fill")
        await move(session, row, next_state, status)
    row.value = {
        **row.value,
        "evidence": [
            *row.value["evidence"],
            {"plan_id": str(plan.id), "status": status, "submitted": False},
        ],
    }
