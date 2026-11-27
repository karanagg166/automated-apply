"""API-side realtime EventHub (Milestone 2): DB-polling bridge from the worker to SSE clients.

The worker and the API are separate processes and the Supabase runtime role allows 5 connections,
so the hub never LISTENs on a dedicated connection. One process-wide poller (started lazily with
the first subscriber, stopped with the last) borrows a pooled connection every `poll_interval`
seconds, reads bounded deltas (`Store.ops_event_feed`) and fans them out to per-client queues.

- Bounded per-client queue: on overflow the backlog is dropped and replaced by ONE `resync` event
  (the client refetches); a consumer that overflows `max_overflows` times is evicted.
- Every event gets a monotonically increasing id; a reconnecting client's Last-Event-ID replays the
  in-memory history (or gets `resync` when it is too old / from another process lifetime).
- API-side actions (dry-run toggle, mute, breaker reset, HITL resolve) `publish` directly.
- Payloads are scrubbed (bus.clean_payload + redact_secrets): ids/labels only, never secrets/OTPs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.browser_v2.redact import redact_secrets
from backend.app.events_v2.bus import clean_payload

logger = logging.getLogger(__name__)

EVENT_TYPES = ("worker.state", "job.discovered", "job.queued", "job.applying_step", "job.applied", "job.failed",
               "job.skipped", "hitl.created", "hitl.resolved", "portal.breaker_changed", "cache.decision",
               "mail.reconciled", "resync")
SECRET_HITL_KINDS = frozenset({"OTP", "CAPTCHA", "AUTH"})
StoreSource = Callable[[], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True)
class HubEvent:
    id: int
    type: str
    at: str
    payload: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {"type": self.type, "at": self.at, "payload": self.payload}


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[HubEvent | None]
    overflows: int = 0
    evicted: bool = False
    delivered: int = 0


def scrub(payload: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = clean_payload(payload)
    return {k: redact_secrets(v, 300) if isinstance(v, str) else v for k, v in cleaned.items()}


def state_event_type(row: Mapping[str, Any]) -> str | None:
    """application_state_events row -> SSE type (None = not surfaced)."""
    target, source = str(row.get("to_state") or ""), row.get("from_state")
    reason = str(row.get("event_type") or "")
    if reason.startswith(("mail_", "email_")) or "confirmation_email" in reason:
        return "mail.reconciled"
    if target == "APPLIED":
        return "job.applied"
    if target == "APPLYING":
        return "job.applying_step"
    if target in ("FAILED", "SUBMISSION_UNKNOWN"):
        return "job.failed"
    if target == "FILTERED_OUT":
        return "job.skipped"
    if target == "SCORED":
        return "job.queued"
    if target == "DISCOVERED" and not source:
        return "job.discovered"
    return None


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class _FeedCursor:
    watermark: datetime
    seen_events: deque[str] = field(default_factory=lambda: deque(maxlen=4000))
    seen_hitl: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    worker: dict[str, Any] | None = None
    breakers: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    baselined: bool = False


class EventHub:
    def __init__(self, source: StoreSource | None = None, *, poll_interval: float = 3.0, queue_size: int = 200,
                 history: int = 500, max_overflows: int = 3, overlap: timedelta = timedelta(seconds=10),
                 feed_limit: int = 200, clock: Callable[[], datetime] | None = None) -> None:
        self.source = source
        self.poll_interval = poll_interval
        self.queue_size = queue_size
        self.max_overflows = max_overflows
        self.overlap = overlap
        self.feed_limit = feed_limit
        self.resume_window = timedelta(minutes=5)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.history: deque[HubEvent] = deque(maxlen=history)
        self.subscribers: set[Subscriber] = set()
        self.seq = 0
        self.closed = False
        self.poll_errors = 0
        self.polls = 0
        self.evictions = 0
        self._poller: asyncio.Task[None] | None = None
        self._cursor: _FeedCursor | None = None

    # --- subscribers --------------------------------------------------------------------------
    def subscribe(self, last_event_id: int | None = None) -> Subscriber:
        if self.closed:
            raise RuntimeError("event_hub_closed")
        sub = Subscriber(asyncio.Queue(maxsize=self.queue_size))
        if last_event_id is not None:
            oldest = self.history[0].id if self.history else self.seq + 1
            if last_event_id > self.seq or last_event_id < oldest - 1:
                self._deliver(sub, self._event("resync", {"reason": "history_gap"}, record=False))
            else:
                for event in self.history:
                    if event.id > last_event_id:
                        self._deliver(sub, event)
        self.subscribers.add(sub)
        self._ensure_poller()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self.subscribers.discard(sub)

    @contextlib.asynccontextmanager
    async def subscription(self, last_event_id: int | None = None) -> AsyncIterator[Subscriber]:
        sub = self.subscribe(last_event_id)
        try:
            yield sub
        finally:
            self.unsubscribe(sub)

    def _deliver(self, sub: Subscriber, event: HubEvent) -> None:
        if sub.evicted:
            return
        try:
            sub.queue.put_nowait(event)
            sub.delivered += 1
            return
        except asyncio.QueueFull:
            pass
        sub.overflows += 1
        while not sub.queue.empty():  # slow consumer: drop its backlog, never block the hub
            sub.queue.get_nowait()
        if sub.overflows >= self.max_overflows:
            sub.evicted = True
            self.evictions += 1
            self.subscribers.discard(sub)
            sub.queue.put_nowait(None)  # the stream ends; EventSource reconnects with a fresh queue
            return
        sub.queue.put_nowait(self._event("resync", {"reason": "slow_consumer", "dropped_after": event.id},
                                         record=False))

    # --- publishing ---------------------------------------------------------------------------
    def _event(self, kind: str, payload: Mapping[str, Any], *, record: bool = True) -> HubEvent:
        if record:
            self.seq += 1
        event = HubEvent(self.seq, kind, self.clock().isoformat(), scrub(payload))
        if record:
            self.history.append(event)
        return event

    async def publish(self, kind: str, payload: Mapping[str, Any]) -> HubEvent:
        if kind not in EVENT_TYPES:
            raise ValueError(f"unknown_event_type:{kind}")
        event = self._event(kind, payload)
        for sub in list(self.subscribers):
            self._deliver(sub, event)
        return event

    async def publish_hitl(self, hitl_id: str, status: str, payload: Mapping[str, Any]) -> HubEvent:
        """API-side resolution: published now and remembered so the poller does not repeat it."""
        if self._cursor is not None:
            self._cursor.seen_hitl.append(f"{hitl_id}:{status}")
        kind = "hitl.created" if status == "OPEN" else "hitl.resolved"
        return await self.publish(kind, {"hitl_id": hitl_id, "status": status, **payload})

    # --- poller -------------------------------------------------------------------------------
    def _ensure_poller(self) -> None:
        if self.source is None or self.closed or (self._poller is not None and not self._poller.done()):
            return
        if self._cursor is not None and self.clock() - self._cursor.watermark > self.resume_window:
            self._cursor = None  # idle for long: start from now instead of replaying hours of rows
        self._poller = asyncio.create_task(self._poll_loop(), name="ops-event-hub-poller")

    async def _poll_loop(self) -> None:
        while self.subscribers and not self.closed:
            await self.poll_once()
            await asyncio.sleep(self.poll_interval)

    async def poll_once(self) -> int:
        """One delta read; returns the number of events published. Never raises."""
        if self.source is None:
            return 0
        cursor = self._cursor or _FeedCursor(watermark=self.clock())
        self._cursor = cursor
        try:
            async with self.source() as store:
                feed = await store.ops_event_feed(cursor.watermark - self.overlap, self.feed_limit)
        except Exception as exc:  # noqa: BLE001 - a DB blip must not kill the stream; retry next tick
            self.poll_errors += 1
            logger.info("event hub poll failed: %s", type(exc).__name__)
            return 0
        self.polls += 1
        published = 0
        for kind, payload in self._translate(cursor, feed):
            await self.publish(kind, payload)
            published += 1
        cursor.baselined = True
        # Quiet ticks still advance the window (the overlap re-reads the last few seconds, deduped by
        # id), so a busy history can never starve newer rows behind the feed limit.
        if len(feed.get("events") or []) < self.feed_limit:
            cursor.watermark = max(cursor.watermark, self.clock() - self.overlap)
        return published

    def _translate(self, cursor: _FeedCursor, feed: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        for row in feed.get("events") or []:
            event_id = str(row.get("id"))
            if event_id in cursor.seen_events:
                continue
            cursor.seen_events.append(event_id)
            created = _parse(row.get("created_at"))
            if created is not None and created > cursor.watermark:
                cursor.watermark = created
            kind = state_event_type(row)
            if kind is not None:
                out.append((kind, {"application_id": row.get("application_id"), "platform": row.get("platform"),
                                   "company": row.get("company_name"), "title": row.get("role_title"),
                                   "state": row.get("to_state"), "from_state": row.get("from_state"),
                                   "step": str(row.get("event_type") or "")[:80], "priority": row.get("priority")}))
        for row in feed.get("hitl") or []:
            key = f"{row.get('id')}:{row.get('status')}"
            if key in cursor.seen_hitl:
                continue
            cursor.seen_hitl.append(key)
            status = str(row.get("status") or "")
            secret = str(row.get("kind")) in SECRET_HITL_KINDS
            out.append(("hitl.created" if status == "OPEN" else "hitl.resolved", {
                "hitl_id": row.get("id"), "application_id": row.get("application_id"),
                "platform": row.get("platform"), "kind": row.get("kind"), "status": status,
                "resolved_via": row.get("resolved_via"),
                "prompt": None if secret else str(row.get("prompt_text") or "")[:200]}))
        worker = feed.get("worker")
        if worker is not None:
            snapshot = {k: worker.get(k) for k in ("desired_state", "dry_run", "observed_state", "current_platform",
                                                    "last_error", "revision")}
            if cursor.worker is not None and snapshot != cursor.worker:
                out.append(("worker.state", {**snapshot, "last_error": str(snapshot.get("last_error") or "")[:200]
                                             or None}))
            cursor.worker = snapshot
        for row in feed.get("breakers") or []:
            platform = str(row.get("platform"))
            values = (row.get("circuit_level"), row.get("circuit_open_until"), row.get("auth_status"),
                      row.get("enabled"))
            previous = cursor.breakers.get(platform)
            if previous is not None and previous != values:
                out.append(("portal.breaker_changed", {
                    "platform": platform, "circuit_level": row.get("circuit_level"),
                    "circuit_open_until": row.get("circuit_open_until"), "auth_status": row.get("auth_status"),
                    "enabled": row.get("enabled"), "reason": str(row.get("circuit_reason") or "")[:200] or None}))
            cursor.breakers[platform] = values
        if not cursor.baselined:
            # The first read only establishes the baseline: rows/flags that existed before the first
            # subscriber connected are not news (the client loads the snapshot over REST).
            return [item for item in out if item[0] not in ("worker.state", "portal.breaker_changed")]
        return out

    # --- lifecycle ----------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"subscribers": len(self.subscribers), "seq": self.seq, "polls": self.polls,
                "poll_errors": self.poll_errors, "evictions": self.evictions,
                "poller_running": self._poller is not None and not self._poller.done()}

    async def close(self) -> None:
        self.closed = True
        for sub in list(self.subscribers):
            while not sub.queue.empty():
                sub.queue.get_nowait()
            sub.queue.put_nowait(None)
        self.subscribers.clear()
        if self._poller is not None:
            self._poller.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poller
            self._poller = None
