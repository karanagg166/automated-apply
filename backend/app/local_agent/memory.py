"""Bounded SQL conversation state. No raw owner messages or model transcripts."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app.dashboard.models import OwnerPreference

MAX_HISTORY = 8
TTL_MINUTES = 10


def context_key(actor):
    return "telegram_context_" + hashlib.sha256(actor.identity.encode()).hexdigest()[:24]


async def load_memory(session, actor):
    row = await session.get(OwnerPreference, context_key(actor), with_for_update=True)
    if row:
        try:
            if datetime.fromisoformat(row.value["expires_at"]) > datetime.now(timezone.utc):
                return dict(row.value)
        except (KeyError, TypeError, ValueError):
            pass
    return {"conversation_id": str(uuid4()), "history": [], "job_ids": [],
        "selected_job_id": None, "project_id": None, "clarification": None}


async def save_memory(session, actor, value):
    row = await session.get(OwnerPreference, context_key(actor), with_for_update=True)
    value = {**value, "history": value.get("history", [])[-MAX_HISTORY:],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTES)).isoformat()}
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=context_key(actor), value=value))
    await session.flush()
    return value


async def record_intent(session, actor, intent):
    value = await load_memory(session, actor)
    value["history"] = [*value.get("history", []), {"category": intent.routing_category,
        "at": datetime.now(timezone.utc).isoformat()}]
    return await save_memory(session, actor, value)


async def reset_memory(session, actor):
    value = {"conversation_id": str(uuid4()), "history": [], "job_ids": [],
        "selected_job_id": None, "project_id": None, "clarification": None}
    return await save_memory(session, actor, value)
