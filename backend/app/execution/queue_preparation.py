"""Bounded queue producers and local preparation; no provider network requests."""

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, or_, select

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import store
from backend.app.execution.queue_contracts import QueuePolicy
from backend.app.models.job import Job


async def seed_saved_sources(session):
    """Consume existing approved records only, with independent durable cursors."""
    current = await queue.configuration(session)
    policy = QueuePolicy.model_validate(current["policy"])
    settings = policy.platforms.get("naukri")
    if current["state"] != "RUNNING" or not settings or not settings.enabled:
        return 0
    await store.memory_row(session, lock=True)
    current = await queue.configuration(session)
    if current["state"] != "RUNNING":
        return 0
    policy = QueuePolicy.model_validate(current["policy"])
    settings = policy.platforms.get("naukri")
    if not settings or not settings.enabled:
        return 0
    added = 0
    for source in ("approved_gmail_alerts", "saved_verified_job"):
        if source not in settings.sources:
            continue
        cursor_key = "apply_source:" + source
        cursor = await session.get(OwnerPreference, cursor_key, populate_existing=True)
        model = OwnerPreference if source == "approved_gmail_alerts" else Job
        identity = model.key if model is OwnerPreference else model.id
        query = select(model).where(
            model.key.startswith("nau_alert:") if model is OwnerPreference else model.source_platform == "naukri"
        )
        if cursor:
            timestamp = datetime.fromisoformat(cursor.value["updated_at"])
            value = cursor.value["id"] if model is OwnerPreference else UUID(cursor.value["id"])
            query = query.where(or_(model.updated_at > timestamp, and_(model.updated_at == timestamp, identity > value)))
        rows = (await session.scalars(query.order_by(model.updated_at, identity).limit(10))).all()
        for row in rows:
            row_id = str(row.key if model is OwnerPreference else row.id)
            # Historical deferred adapters or other mailboxes cannot become a
            # newly authorized source merely because a queue was enabled.
            value = row.value if model is OwnerPreference else None
            permitted = value is None or (value.get("source") == "gmail_job_alerts" and value.get("account_id") == "local:1")
            url = value.get("url") if value else row.job_url
            if permitted:
                try:
                    before = await session.scalar(select(OwnerPreference.key).where(
                        OwnerPreference.key == queue.PREFIX + str(uuid5(NAMESPACE_URL, "naukri:" + queue.normalized_url(url).rsplit("-", 1)[-1]))
                    ))
                    await queue.enqueue(session, "naukri", url, source, row_id)
                    added += int(before is None)
                except ToolDenied as exc:
                    if str(exc) == "queue_backpressure":
                        return added  # Leave this record behind the cursor.
                    if str(exc) not in {"prior_receipt_requires_reconciliation_no_replay", "prior_application_or_unknown_submission_no_replay"}:
                        raise
                except ValueError:
                    pass  # Unsupported URL remains in its original source, not a fabricated vacancy.
            await queue.put(session, cursor_key, {"updated_at": row.updated_at.isoformat(), "id": row_id})
    return added


async def prepare_one(session, settings):
    """Actual queued job -> verified matching -> persisted packet, one per tick."""
    config = await queue.configuration(session)
    policy = QueuePolicy.model_validate(config["policy"])
    platform = policy.platforms["naukri"]
    if config["state"] != "RUNNING" or not platform.enabled:
        return False
    # A browser-inspection backlog is not preparation work. Previously every
    # idle worker tick took the shared owner lock and rescanned that backlog,
    # contending with the native requests that could actually advance it.
    # This is only a scheduling hint: claim still rechecks policy and leases
    # under the original lock. A racing enqueue waits for the next tick.
    candidates = (await session.scalars(select(OwnerPreference.value).where(
        OwnerPreference.key.startswith(queue.PREFIX),
        OwnerPreference.value["platform"].as_string() == "naukri",
        OwnerPreference.value["stage"].as_string().not_in(queue.TERMINAL),
        or_(
            and_(OwnerPreference.value["operation"].as_string() == "prepare",
                 OwnerPreference.value["status"].as_string() == "queued"),
            and_(OwnerPreference.value["stage"].as_string() == "READY_TO_APPLY",
                 OwnerPreference.value["status"].as_string() == "waiting"),
            OwnerPreference.value["status"].as_string().in_(["leased", "executing"]),
        ),
    ))).all()
    pending = any(
        (v["operation"] == "prepare" and v["status"] == "queued")
        or (v["stage"] == "READY_TO_APPLY" and v["status"] == "waiting"
            and platform.mode in {"AUTOMATIC", "SUPERVISED"}
            and platform.owner_submission_authorized and not v.get("admitted_actions"))
        for v in candidates
    )
    leases = [v for v in candidates if v["status"] in {"leased", "executing"} and v.get("lease_until")]
    if not pending and leases:
        now = await instant(session)
        # Keep claim's recovery of ALL expired leases, especially a possible
        # Apply. Never leave that action resumable or turn it into preparation.
        pending = any(datetime.fromisoformat(v["lease_until"]) <= now for v in leases)
    if not pending:
        return False
    if config["state"] == "RUNNING" and platform.enabled and platform.mode in {"AUTOMATIC", "SUPERVISED"} and platform.owner_submission_authorized:
        await store.memory_row(session, lock=True)
        for waiting in await queue.items(session, active_only=True):
            v = dict(waiting.value)
            if v["stage"] == "READY_TO_APPLY" and v["status"] == "waiting" and not v.get("admitted_actions"):
                waiting.value = {**v, "operation": "prepare", "status": "queued", "reason": None, "revision": v["revision"] + 1}
                await queue.event(session, waiting.value, "standing_policy_requires_fresh_preparation")
                break
    value = await queue.claim(session, "naukri", {"worker": "local_preparation"}, operations={"prepare"})
    if not value:
        return False
    row = await queue.load(session, value["id"])
    value = dict(row.value)
    policy = QueuePolicy.model_validate((await queue.configuration(session))["policy"])
    try:
        job = await session.get(Job, UUID(value["job_id"]), populate_existing=True)
        if not job or await store.previously_applied(session, job):
            raise ToolDenied("prior_application_or_unknown_submission_no_replay")
        profile = await queue.eligible_context(session, value, policy, job)
        value.update(stage="ELIGIBLE", profile_version=profile.version)
        value["revision"] += 1
        await queue.event(session, value, "eligibility_verified")
        from backend.app.models.application_packet import ApplicationPacket
        from backend.app.schemas.applications import CreatePacket
        from backend.app.services.applications.service import ApplicationPacketService

        value.update(stage="PREPARING", revision=value["revision"] + 1)
        await queue.event(session, value, "preparing")
        service = ApplicationPacketService(session)
        existing = await session.scalar(select(ApplicationPacket.id).where(
            ApplicationPacket.job_id == job.id, ApplicationPacket.candidate_profile_id == profile.id,
        ))
        packet = await service.read(existing) if existing else await service.create(job.id, CreatePacket(idempotency_key="queue_" + value["id"]))
        from backend.app.execution.naukri_upload import preflight

        checked = await preflight(session, packet, settings)
        value.update(packet_id=str(packet.id), packet_revision=packet.revision, upload_preflight=checked)
        if checked["state"] != "PDF_VERIFIED_LOCAL":
            raise ToolDenied(checked["reason"])
        if packet.readiness.state in {"needs_input", "needs_resume", "needs_profile"}:
            raise ToolDenied("packet_factual_input_required")
        # The background consumer in this release is read-only. An AUTOMATIC
        # preference is never mistaken for a delivered submission capability.
        automatic = policy.platforms["naukri"].mode in {"AUTOMATIC", "SUPERVISED"} and policy.platforms["naukri"].owner_submission_authorized
        from backend.app.execution.naukri_identity import require

        account = await require(session, profile.id)
        value.update(stage="READY_TO_APPLY", reason=None if automatic else "automatic_submission_scope_required",
                     status="queued" if automatic else "waiting", operation="inspect_profile",
                     candidate_profile_id=str(profile.id), account_binding_revision=account["revision"],
                     account_sha256=account["account_sha256"])
    except ToolDenied as exc:
        queue.eligibility_hold(value, str(exc))
    value.update(lease_token=None, lease_until=None, updated_at=(await instant(session)).isoformat(), revision=value["revision"] + 1)
    row.value = value
    await queue.event(session, value, "preparation_finished")
    return True
