"""Server-Sent Events framing + the bounded per-client stream loop for the EventHub."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from backend.app.events_v2.hub import EventHub, HubEvent, Subscriber

HEARTBEAT = ": ping\n\n"
RETRY_MS = 3000


def format_event(event: HubEvent) -> str:
    data = json.dumps(event.public(), default=str, separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"


def parse_last_event_id(value: str | None) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


async def event_stream(hub: EventHub, sub: Subscriber, *, heartbeat_sec: float = 15.0,
                       max_seconds: float = 75.0, check_every: float = 1.0,
                       is_disconnected: Callable[[], Awaitable[bool]] | None = None,
                       monotonic: Callable[[], float] = time.monotonic) -> AsyncIterator[str]:
    """Yield SSE frames until the client leaves, the hub shuts down / evicts us, or `max_seconds`
    pass (the dashboard proxy aborts long requests; EventSource reconnects with Last-Event-ID)."""
    started = last_sent = monotonic()
    try:
        yield f"retry: {RETRY_MS}\n\n"
        while True:
            now = monotonic()
            remaining = max_seconds - (now - started)
            if remaining <= 0:
                return
            wait = max(0.01, min(check_every, remaining, heartbeat_sec - (now - last_sent)))
            try:
                item = await asyncio.wait_for(sub.queue.get(), timeout=wait)
            except TimeoutError:
                if is_disconnected is not None and await is_disconnected():
                    return
                if monotonic() - last_sent >= heartbeat_sec:
                    last_sent = monotonic()
                    yield HEARTBEAT
                continue
            if item is None:  # hub closed or this slow consumer was evicted
                return
            last_sent = monotonic()
            yield format_event(item)
    finally:
        hub.unsubscribe(sub)
