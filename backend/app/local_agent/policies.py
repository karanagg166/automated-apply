"""Preferences never confer execution capabilities. Updates use compare-and-swap."""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.app.local_agent.contracts import PLATFORMS, PolicyUpdate
from backend.app.local_agent.models import AgentPolicy, PolicyEvent


def initial_policy():
    return {"default": "approve", "platforms": {
        name: "automatic_preferred" if name == "naukri" else
        "draft_only" if name == "gmail" else "manual_only" if name == "linkedin" else "approve"
        for name in PLATFORMS
    }}


async def get_policy(session):
    row = await session.get(AgentPolicy, "primary")
    return {"version": row.version, **row.preferences} if row else {"version": 1, **initial_policy()}


async def update_policy(session, data: PolicyUpdate):
    if set(data.platforms) != set(PLATFORMS):
        raise ValueError("invalid_policy_platforms")
    if data.platforms["gmail"] not in {"draft_only", "disabled"} or data.platforms["linkedin"] not in {"manual_only", "disabled"}:
        raise ValueError("fixed_platform_policy")
    preferences = {"default": data.default, "platforms": data.platforms}
    row = await session.get(AgentPolicy, "primary")
    if row is None:
        if data.expected_version != 1:
            raise ValueError("policy_version_conflict")
        try:
            async with session.begin_nested():
                session.add(AgentPolicy(key="primary", version=2, preferences=preferences))
                await session.flush()
        except IntegrityError:
            raise ValueError("policy_version_conflict") from None
    else:
        changed = await session.execute(update(AgentPolicy).where(
            AgentPolicy.key == "primary", AgentPolicy.version == data.expected_version,
        ).values(version=data.expected_version + 1, preferences=preferences))
        if changed.rowcount != 1:
            raise ValueError("policy_version_conflict")
    session.add(PolicyEvent(version=data.expected_version + 1, preferences=preferences))
    await session.flush()
    return {"version": data.expected_version + 1, **preferences}


def evaluate(policy, platform, capability):
    preference = policy["platforms"].get(platform, policy["default"])
    return {
        "preference": preference,
        "preview_allowed": preference != "disabled",
        "submission_allowed": False,
        "email_send_allowed": False,
        "paid_calls_allowed": False,
        "capability": capability,
        "reason": "phase1_preview_only",
    }
