"""v2 control plane: the LLM-first control agent chat (Phase 9C) and the event-bus status."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.v2.deps import AIDep, StoreDep
from backend.app.browser_v2.schemas import (
    AgentChatInput,
    AgentChatRead,
    EventBusStatusRead,
)

router = APIRouter()


# --- Phase 6A: control agent, event bus, read-only recruiter replies ----------------------
@router.post("/agent/chat", response_model=AgentChatRead)
async def agent_chat(data: AgentChatInput, store: StoreDep, ai: AIDep) -> AgentChatRead:
    """The same LLM-first agent as Telegram free chat (audited, guardrailed tools only; it can never
    send email, delete data or re-apply; deterministic fallback without an LLM provider). Risky
    writes need a follow-up "confirm" within 10 minutes. Effects use the borrowed pooled connection."""
    from backend.app.agent_v2.control_graph import ControlAgent
    from backend.app.browser_v2.store import agent_chat_key
    from backend.app.mail_v2.reader import MailEventStore

    connection = getattr(store, "connection", None)
    events = MailEventStore(connection) if connection is not None and await MailEventStore.ready(connection) else None
    result = await ControlAgent(store, ai=ai, mail_events=events).run_chat(
        data.text, chat_key=agent_chat_key("api", "dashboard"), source="api")
    return AgentChatRead(reply=result["reply"], tool=result.get("tool"), source=result.get("source"),
                         verdict=result.get("verdict"), ok=bool(result.get("ok")))


@router.get("/events/status", response_model=EventBusStatusRead)
async def events_status() -> EventBusStatusRead:
    from backend.app.ai_v2.router import load_env
    from backend.app.events_v2.bus import build_event_bus, bus_status

    env = load_env()
    bus = build_event_bus(env)
    try:
        status = await bus_status(bus, env)
    finally:
        await bus.close()
    return EventBusStatusRead(**{k: status[k] for k in ("backend", "requested_backend", "fell_back", "healthy",
                                                         "published", "handler_errors", "topics", "remote")})
