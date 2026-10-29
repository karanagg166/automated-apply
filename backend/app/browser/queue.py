"""Browser jobs are durable private records; the Telegram worker never owns Chrome."""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from backend.app.agent import store
from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference


async def enqueue(session, settings, campaign, job, inspect_only=False):
    from backend.app.browser.service import FormService
    from backend.app.models.application_packet import ApplicationPacket

    if not settings.BROWSER_AUTOMATION_ENABLED or (
        not inspect_only and not settings.BROWSER_FILL_ENABLED
    ):
        return {"status": "capability_not_enabled", "submitted": False}
    approval = campaign.approval
    if not inspect_only and (
        not approval
        or approval.scope != "fill"
        or approval.expected_revision != campaign.revision
        or approval.nonce != campaign.approval_nonce
        or len(campaign.plan.selected_jobs) > approval.maximum_applications
    ):
        raise ToolDenied("fill_scope_required")
    packet = await session.scalar(
        select(ApplicationPacket).where(ApplicationPacket.job_id == job.id)
    )
    if not packet:
        return {
            "status": "needs_input",
            "missing_information": ["Prepare an application draft first."],
            "submitted": False,
        }
    _, _, url = await FormService(session, settings).context(packet.id)
    from backend.app.local_agent.contracts import page_kind

    if not inspect_only and page_kind(url) not in approval.platforms:
        raise ToolDenied("platform_outside_fill_scope")
    key = "browser_job:" + str(uuid5(NAMESPACE_URL, f"{campaign.id}:{job.id}"))
    prior = await session.get(OwnerPreference, key)
    if prior:
        return {"status": prior.value["state"], "browser_job": key, "submitted": False}
    now = await instant(session)
    session.add(
        OwnerPreference(
            key=key,
            value={
                "id": str(uuid4()),
                "campaign_id": str(campaign.id),
                "application_id": str(packet.id),
                "selected_project": campaign.selected_project,
                "inspect_only": inspect_only,
                "state": "queued",
                "fence": 0,
                "lease_until": None,
                "attempts": 0,
                "step_count": 1,
                "plan_id": None,
                "expires_at": (now + timedelta(minutes=15)).isoformat(),
                "result": None,
            },
        )
    )
    return {
        "status": "pending_browser",
        "browser_job": key,
        "application_id": str(packet.id),
        "submitted": False,
    }


async def claim(session):
    await store.memory_row(session, lock=True)
    now = await instant(session)
    submitting = (await session.scalars(select(OwnerPreference.value).where(
        OwnerPreference.key.like("submission:%"), OwnerPreference.value["state"].as_string() == "submitting"))).all()
    if any(v.get("lease_until") and datetime.fromisoformat(v["lease_until"]) > now for v in submitting):
        return None
    active = (
        await session.scalars(
            select(OwnerPreference.value).where(
                OwnerPreference.key.like("browser_job:%"),
                OwnerPreference.value["state"].as_string() == "running",
            )
        )
    ).all()
    if any(
        value.get("lease_until") and datetime.fromisoformat(value["lease_until"]) > now
        for value in active
    ):
        return None
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(OwnerPreference.key.like("browser_job:%"))
            .order_by(OwnerPreference.created_at)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if any(
        r.value["state"] == "running"
        and datetime.fromisoformat(r.value["lease_until"]) > now
        for r in rows
    ):
        return None
    for row in rows:
        job = dict(row.value)
        if job["state"] == "running":
            # A lost browser response can mean fields changed. Never replay side effects.
            job.update(
                state="manual_required",
                result={
                    "status": "manual_required",
                    "error_code": "browser_interrupted_check_form_manually",
                    "submitted": False,
                },
            )
            row.value = job
            await finish_campaign(session, job)
        elif job["state"] == "awaiting_review":
            plan = await session.get(OwnerPreference, "fill_plan:" + job["plan_id"])
            if plan and plan.value["state"] == "authorized":
                job["state"] = "queued"
                row.value = job
        if job["state"] != "queued":
            continue
        _, campaign = await store.load(session, UUID(job["campaign_id"]))
        if (
            campaign.state == "cancelled"
            or datetime.fromisoformat(job["expires_at"]) <= now
        ):
            job.update(
                state="manual_required",
                result={
                    "status": "manual_required",
                    "error_code": "campaign_expired_or_cancelled",
                    "submitted": False,
                },
            )
            row.value = job
            await finish_campaign(session, job)
            continue
        job.update(
            state="running",
            fence=job["fence"] + 1,
            attempts=job["attempts"] + 1,
            lease_until=(now + timedelta(seconds=90)).isoformat(),
        )
        row.value = job
        return row.key, job
    return None


async def fenced(session, key, fence):
    row = await session.get(
        OwnerPreference, key, with_for_update=True, populate_existing=True
    )
    job = dict(row.value)
    now = await instant(session)
    _, campaign = await store.load(session, UUID(job["campaign_id"]))
    if (
        job["state"] != "running"
        or job["fence"] != fence
        or datetime.fromisoformat(job["lease_until"]) <= now
        or campaign.state == "cancelled"
        or datetime.fromisoformat(job["expires_at"]) <= now
    ):
        raise ToolDenied("browser_lease_lost")
    return row, job


async def finish_campaign(session, job):
    from backend.app.agent.executor import summary

    row, campaign = await store.load(session, UUID(job["campaign_id"]), lock=True)
    campaign.results = [
        r
        for r in campaign.results
        if r.get("application_id") != job["application_id"]
        or r.get("tool") not in {"fill_application", "inspect_application"}
    ]
    campaign.results.append(
        {
            "tool": "inspect_application"
            if job["inspect_only"]
            else "fill_application",
            "application_id": job["application_id"],
            **job["result"],
        }
    )
    pending = any(
        r.get("status") in {"pending_browser", "awaiting_review"}
        for r in campaign.results
    )
    if campaign.state == "waiting_browser" and not pending:
        incomplete = any(
            r.get("status")
            in {"needs_input", "manual_required", "failed", "denied", "cancelled"}
            for r in campaign.results
        )
        store.transition(
            campaign,
            "partially_completed" if incomplete else "completed",
            await instant(session),
            "browser_work_finished",
        )
    campaign.reply = summary(campaign)
    store.save(row, campaign)
    await store.notify(session, campaign)


async def stop_all(session):
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(OwnerPreference.key.like("browser_job:%"))
            .with_for_update()
        )
    ).all()
    for row in rows:
        job = dict(row.value)
        if job["state"] in {
            "queued",
            "running",
            "awaiting_review",
            "confirmation_required",
        }:
            job.update(state="cancelled", fence=job["fence"] + 1, lease_until=None)
            job["result"] = {"status": "cancelled", "submitted": False}
            row.value = job
            await finish_campaign(session, job)
    # Revokes outstanding manual and local grants, including already consumed ones.
    plans = (
        await session.scalars(
            select(OwnerPreference)
            .where(OwnerPreference.key.like("fill_plan:%"))
            .with_for_update()
        )
    ).all()
    for row in plans:
        if row.value.get("extension_task_id") and row.value.get("state") == "consumed":
            # A consumed plan cannot authorize another fill. Keep it available
            # solely for the interrupted worker's eventual partial audit receipt.
            continue
        row.value = {**row.value, "state": "finished"}
