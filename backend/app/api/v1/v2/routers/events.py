"""Realtime ops stream (Server-Sent Events) bridged from the DB-polling EventHub."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.events_v2.hub import EventHub
from backend.app.events_v2.sse import event_stream, parse_last_event_id

router = APIRouter()
STREAM_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_HUB: EventHub | None = None


@asynccontextmanager
async def api_store_source() -> AsyncIterator[Any]:
    """One short-lived pooled session per poll tick (never a dedicated LISTEN connection)."""
    from backend.app.browser_v2.store import PostgresStore
    from backend.app.db.session import get_session_factory

    async with get_session_factory()() as session:
        connection = await session.connection()
        if connection.dialect.name != "postgresql":
            raise RuntimeError("event hub requires PostgreSQL")
        raw = await connection.get_raw_connection()
        yield await PostgresStore.borrowed(raw.driver_connection)


def get_event_hub() -> EventHub:
    """Process-wide hub (lazily created; closed by the app lifespan via `close_event_hub`)."""
    global _HUB
    if _HUB is None or _HUB.closed:
        _HUB = EventHub(api_store_source)
    return _HUB


async def close_event_hub() -> None:
    global _HUB
    if _HUB is not None:
        await _HUB.close()
        _HUB = None


HubDep = Annotated[EventHub, Depends(get_event_hub)]


@router.get("/events/stream", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}},
                             "description": "SSE frames: `id`, `event` (type) and JSON `data` {type, at, payload}; "
                                            "`: ping` heartbeats every 15 s; the stream ends after ~75 s "
                                            "(reconnect with Last-Event-ID)."}})
async def ops_event_stream(
    request: Request, hub: HubDep,
    last_event_header: Annotated[str | None, Header(alias="Last-Event-ID", max_length=20)] = None,
    last_event_id: Annotated[int | None, Query(ge=0, le=10**12,
                                               description="Resume point when the client cannot set "
                                                           "the Last-Event-ID header (manual reconnect)")] = None,
) -> StreamingResponse:
    resume = parse_last_event_id(last_event_header)
    sub = hub.subscribe(resume if resume is not None else last_event_id)
    stream = event_stream(hub, sub, is_disconnected=request.is_disconnected)
    return StreamingResponse(stream, media_type="text/event-stream", headers=STREAM_HEADERS)
