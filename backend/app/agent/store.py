"""Durable campaigns on the existing private operation store; no schema/DDL changes.

Short PostgreSQL row locks serialize the singleton owner's claims. A fencing token
invalidates stale workers. Preparation writes and progress share one transaction.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select

from backend.app.agent.contracts import Approval, Campaign, Filters, Message, Plan
from backend.app.agent.tools import ToolDenied, owner_allowed
from backend.app.automation.store import instant
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.models import AgentOperation, TelegramDelivery
from backend.app.services.discovery_budget import insert_for

MEMORY_KEY = "agent_conversation:primary"
TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}
TRANSITIONS = {
    "created": {"queued", "cancelled"}, "queued": {"running", "cancelled", "failed"},
    "running": {"planned", "awaiting_approval", "completed", "partially_completed", "failed", "cancelled", "queued"},
    "planned": {"running", "awaiting_approval", "cancelled"},
    "awaiting_approval": {"queued", "cancelled"},
    **{state: set() for state in TERMINAL},
}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def transition(campaign, state, now, reason=None):
    if state not in TRANSITIONS[campaign.state]:
        raise ToolDenied("invalid_campaign_transition")
    campaign.history.append({"from": campaign.state, "to": state, "at": now.isoformat(), "reason": reason})
    campaign.state, campaign.updated_at = state, now.isoformat()


async def memory_row(session, *, lock=False):
    await session.execute(insert_for(session)(OwnerPreference).values(key=MEMORY_KEY, value={}).on_conflict_do_nothing())
    query = select(OwnerPreference).where(OwnerPreference.key == MEMORY_KEY).execution_options(populate_existing=True)
    return await session.scalar(query.with_for_update() if lock else query)


def bounded_memory(row, now):
    value = dict(row.value)
    if not value.get("updated_at") or utc(datetime.fromisoformat(value["updated_at"])) < now - timedelta(hours=24):
        return {}
    return value


async def campaigns(session, limit=50):
    return (await session.scalars(select(OwnerPreference).where(OwnerPreference.key.like("campaign:%")).order_by(
        OwnerPreference.created_at.desc(), OwnerPreference.key).limit(limit))).all()


async def load(session, campaign_id, *, lock=False):
    row = await session.get(OwnerPreference, f"campaign:{campaign_id}", with_for_update=lock, populate_existing=True)
    if row is None:
        raise ToolDenied("campaign_not_found")
    return row, Campaign.model_validate(row.value)


def save(row, campaign):
    row.value = campaign.model_dump(mode="json")


async def intake(session, settings, actor, message: Message, *, telegram_update_id=None):
    if not owner_allowed(actor, settings):
        raise ToolDenied("authenticated_owner_required")
    now = await instant(session)
    memory = await memory_row(session, lock=True)
    key = f"agent_intake:primary:{message.request_id}"
    digest = hashlib.sha256(message.text.encode()).hexdigest()
    previous = await session.get(AgentOperation, key)
    if previous:
        if previous.payload_hash != digest:
            raise ToolDenied("request_id_conflict")
        return (await load(session, UUID(previous.result["campaign_id"])))[1]
    # Admission bounds persisted pending work, including approval waits. Controls bypass the queue.
    from backend.app.agent.planner import deterministic
    understanding = deterministic(message.text)
    context = bounded_memory(memory, now)
    if understanding and (understanding.intent == "cancel" or
                          (understanding.intent == "status" and "applications" not in message.text.casefold())):
        target = (context.get("result_campaign") if understanding.intent == "status" and "search" in message.text.casefold()
                  else context.get("pending_campaign") or context.get("last_campaign"))
        if target:
            row, existing = await load(session, UUID(target), lock=True)
            if understanding.intent == "cancel" and existing.state not in TERMINAL:
                transition(existing, "cancelled", now, "owner_cancelled")
                existing.fence += 1
                existing.lease_until = None
                existing.reply = "Campaign cancelled. Zero submissions were made."
                save(row, existing)
            session.add(AgentOperation(key=key, actor=f"{actor.channel}:{actor.identity}", command="agent_intake",
                                       payload_hash=digest, result={"campaign_id": str(existing.id)}))
            return existing
    pending_count = await session.scalar(select(func.count()).select_from(OwnerPreference).where(
        OwnerPreference.key.like("campaign:%"), OwnerPreference.value["state"].as_string().not_in(TERMINAL)))
    if pending_count >= 10:
        raise ToolDenied("pending_campaign_limit")
    campaign = Campaign(id=uuid4(), message=message.text, actor=f"{actor.channel}:{actor.identity}",
        plan=Plan(intent="clarify", filters=Filters()), created_at=now.isoformat(), updated_at=now.isoformat(),
        telegram_update_id=telegram_update_id)
    transition(campaign, "queued", now, "owner_command_accepted")
    session.add(OwnerPreference(key=f"campaign:{campaign.id}", value=campaign.model_dump(mode="json")))
    session.add(AgentOperation(key=key, actor=campaign.actor, command="agent_intake", payload_hash=digest,
                               result={"campaign_id": str(campaign.id)}))
    memory.value = {**context, "pending_campaign": str(campaign.id), "updated_at": now.isoformat()}
    await session.flush()
    return campaign


async def claim(session):
    # One writer/owner even across two worker processes. No row lock survives commit.
    await memory_row(session, lock=True)
    now = await instant(session)
    active = (await session.scalars(select(OwnerPreference.value).where(
        OwnerPreference.key.like("campaign:%"), OwnerPreference.value["state"].as_string() == "running"))).all()
    # A lease holder's row may be locked by its heartbeat/planning transaction. A
    # plain MVCC read prevents SKIP LOCKED from hiding it and admitting another task.
    if any(value.get("lease_until") and utc(datetime.fromisoformat(value["lease_until"])) > now for value in active):
        return None
    rows = (await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.like("campaign:%"),
        OwnerPreference.value["state"].as_string().in_(["queued", "running"])).order_by(
            OwnerPreference.created_at, OwnerPreference.key).with_for_update(skip_locked=True).limit(10))).all()
    # An unexpired owner lease takes precedence over all queued commands.
    for row in rows:
        c = Campaign.model_validate(row.value)
        if c.state == "running" and c.lease_until and utc(datetime.fromisoformat(c.lease_until)) > now:
            return None
    for row in rows:
        campaign = Campaign.model_validate(row.value)
        if campaign.state == "running":
            transition(campaign, "queued", now, "expired_lease_recovered")
        if campaign.attempts >= 3:
            transition(campaign, "failed", now, "retry_limit")
            campaign.reply, campaign.diagnostic = "Campaign failed after bounded recovery. Zero submissions were made.", "retry_limit"
            save(row, campaign)
            continue
        campaign.attempts += 1
        campaign.fence += 1
        campaign.lease_until = (now + timedelta(seconds=120)).isoformat()
        campaign.heartbeat_at = now.isoformat()
        transition(campaign, "running", now, "claimed")
        save(row, campaign)
        return campaign
    return None


async def fenced(session, campaign_id, fence):
    row, campaign = await load(session, campaign_id, lock=True)
    now = await instant(session)
    if (campaign.state != "running" or campaign.fence != fence or not campaign.lease_until or
            utc(datetime.fromisoformat(campaign.lease_until)) <= now):
        raise ToolDenied("lease_or_fence_lost")
    return row, campaign


async def heartbeat(factory, campaign_id, fence):
    async with factory() as session:
        row, campaign = await fenced(session, campaign_id, fence)
        now = await instant(session)
        campaign.heartbeat_at, campaign.lease_until = now.isoformat(), (now + timedelta(seconds=120)).isoformat()
        save(row, campaign)
        await session.commit()


async def approve(session, settings, actor, campaign_id, approval: Approval):
    if not owner_allowed(actor, settings):
        raise ToolDenied("authenticated_owner_required")
    row, campaign = await load(session, campaign_id, lock=True)
    if (approval.scope != "prepare" or campaign.state != "awaiting_approval" or
            approval.expected_revision != campaign.revision or approval.nonce != campaign.approval_nonce or
            not campaign.plan.selected_jobs or len(campaign.plan.selected_jobs) > approval.maximum_applications):
        raise ToolDenied("approval_rejected")
    campaign.approval = approval
    transition(campaign, "queued", await instant(session), "owner_approved_drafts_only")
    save(row, campaign)
    return campaign


async def cancel(session, settings, actor, campaign_id):
    if not owner_allowed(actor, settings):
        raise ToolDenied("authenticated_owner_required")
    await memory_row(session, lock=True)
    row, campaign = await load(session, campaign_id, lock=True)
    if campaign.state not in TERMINAL:
        transition(campaign, "cancelled", await instant(session), "owner_cancelled")
        campaign.fence += 1
        campaign.lease_until = None
        campaign.reply = "Campaign cancelled. Zero submissions were made."
        save(row, campaign)
    return campaign


async def notify(session, campaign):
    if campaign.telegram_update_id is None:
        return
    original = await session.get(TelegramDelivery, campaign.telegram_update_id, with_for_update=True)
    if original and original.state == "pending":
        original.reply = campaign.reply
    else:
        # A separate unique outbox item if acceptance was already dispatched. Ambiguous sends stay sending.
        await session.execute(insert_for(session)(TelegramDelivery).values(
            update_id=-campaign.telegram_update_id - 1, reply=campaign.reply, state="pending").on_conflict_do_nothing())
