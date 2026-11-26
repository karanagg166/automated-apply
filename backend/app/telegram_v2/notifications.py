"""Early-bird Telegram notifications (Phase 9B), fed by the event bus.

- `job.priority_discovered` (P0 only): batched, <= 1 message per 2 minutes, <= 5 jobs each;
  unsupported-ATS jobs carry their manual apply link.
- `job.applied`: only for P0/P1 rows (payload `priority`, else looked up in the store).
- `portal.circuit_open`: one alert per portal per 30 minutes (operational: always sent).
Daily cap of 30 messages across all types. The owner preference `notify_early_bird`
(default True) silences discovery/applied messages. HTML is escaped with `formatting._e`.
A handler never raises into the bus: every failure is logged and swallowed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.app.telegram_v2.formatting import _e

logger = logging.getLogger(__name__)

TOPICS = ("job.priority_discovered", "job.applied", "portal.circuit_open")
BATCH_INTERVAL = timedelta(minutes=2)
APPLIED_INTERVAL = timedelta(minutes=1)
CIRCUIT_REPEAT = timedelta(minutes=30)
MAX_JOBS_PER_MESSAGE = 5
MAX_PENDING = 50
DAILY_CAP = 30
Clock = Callable[[], datetime]
PrefsProvider = Callable[[], Awaitable[Mapping[str, Any]]]
Sleeper = Callable[[float], Awaitable[Any]]


def _priority(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _who(payload: Mapping[str, Any]) -> str:
    parts = [_e(payload.get("company"), 80), _e(payload.get("title"), 120)]
    return " · ".join(p for p in parts if p) or _e(payload.get("external_job_id"), 60)


def render_discoveries(jobs: Sequence[Mapping[str, Any]]) -> str:
    lines = [f"⚡ <b>{len(jobs)} early-bird job{'s' if len(jobs) != 1 else ''}</b> (P0)"]
    for job in jobs:
        line = f"• <b>{_e(job.get('platform'), 30)}</b> {_who(job)}"
        if job.get("url"):
            line += f"\n  {_e(job.get('url'), 300)}"
        if job.get("ats_supported") is False and job.get("apply_url"):
            line += f"\n  Manual apply: {_e(job.get('apply_url'), 300)}"
        lines.append(line)
    return "\n".join(lines)


def render_applied(payload: Mapping[str, Any], priority: int) -> str:
    return f"✅ <b>Applied</b> (P{priority}) · <b>{_e(payload.get('platform'), 30)}</b> {_who(payload)}"


def render_circuit(payload: Mapping[str, Any]) -> str:
    text = f"🛑 <b>{_e(payload.get('platform'), 40)}</b> paused by its circuit breaker"
    if payload.get("open_until") or payload.get("until"):
        text += f" until {_e(payload.get('open_until') or payload.get('until'), 40)}"
    if payload.get("reason"):
        text += f"\nReason: {_e(payload.get('reason'), 200)}"
    return text + "\nOther portals keep running."


class EarlyBirdNotifier:
    def __init__(self, client: Any, chat_id: int | None, clock: Clock | None = None, *,
                 prefs_provider: PrefsProvider | None = None, store: Any = None,
                 sleeper: Sleeper | None = None, auto_flush: bool = True) -> None:
        self.client = client
        self.chat_id = chat_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.prefs_provider = prefs_provider
        self.store = store
        self.sleeper = sleeper or asyncio.sleep
        self.auto_flush = auto_flush
        self.pending: list[dict[str, Any]] = []
        self.last_sent: dict[str, datetime] = {}
        self.circuit_sent: dict[str, datetime] = {}
        self.day: date | None = None
        self.sent_today = 0
        self.dropped = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # --- bus entry point -----------------------------------------------------------------------
    async def handle(self, topic: str, payload: Mapping[str, Any]) -> None:
        try:
            if topic == "job.priority_discovered":
                await self.on_discovered(payload)
            elif topic == "job.applied":
                await self.on_applied(payload)
            elif topic == "portal.circuit_open":
                await self.on_circuit_open(payload)
        except Exception as exc:  # noqa: BLE001 - never raise into the bus
            logger.warning("early-bird notifier %s failed: %s", topic, type(exc).__name__)

    async def enabled(self) -> bool:
        if self.prefs_provider is None:
            return True
        try:
            prefs = await self.prefs_provider()
        except Exception:  # noqa: BLE001 - unreadable profile: keep the default (on)
            return True
        return (prefs or {}).get("notify_early_bird") is not False

    async def on_discovered(self, payload: Mapping[str, Any]) -> None:
        if _priority(payload.get("priority")) != 0 or not await self.enabled():
            return
        key = (payload.get("platform"), payload.get("external_job_id"))
        if any((job.get("platform"), job.get("external_job_id")) == key for job in self.pending):
            return
        if len(self.pending) >= MAX_PENDING:
            self.dropped += 1
            return
        self.pending.append(dict(payload))
        await self.flush()

    async def flush(self) -> bool:
        """Send one batch if the 2-minute window is open; otherwise schedule a delayed flush."""
        async with self._lock:
            if not self.pending:
                return False
            wait = self._wait("discovery", BATCH_INTERVAL)
            if wait > 0:
                self._schedule(wait)
                return False
            batch = self.pending[:MAX_JOBS_PER_MESSAGE]
            if not await self._send("discovery", render_discoveries(batch)):
                return False
            del self.pending[:len(batch)]
            if self.pending:
                self._schedule(BATCH_INTERVAL.total_seconds())
            return True

    async def on_applied(self, payload: Mapping[str, Any]) -> None:
        priority = _priority(payload.get("priority"))
        if priority is None and self.store is not None and payload.get("platform") and payload.get("external_job_id"):
            record = await self.store.get(payload["platform"], payload["external_job_id"])
            priority = _priority(getattr(record, "priority", None))
        if priority is None or priority > 1 or not await self.enabled():
            return
        if self._wait("applied", APPLIED_INTERVAL) > 0:
            self.dropped += 1
            return
        await self._send("applied", render_applied(payload, priority))

    async def on_circuit_open(self, payload: Mapping[str, Any]) -> None:
        platform = str(payload.get("platform") or "unknown")
        now = self.clock()
        last = self.circuit_sent.get(platform)
        if last is not None and now - last < CIRCUIT_REPEAT:
            return
        if await self._send("circuit", render_circuit(payload)):
            self.circuit_sent[platform] = now

    # --- rate limits / delivery --------------------------------------------------------------------
    def _wait(self, kind: str, interval: timedelta) -> float:
        last = self.last_sent.get(kind)
        if last is None:
            return 0.0
        return max(0.0, (last + interval - self.clock()).total_seconds())

    def _schedule(self, delay: float) -> None:
        if not self.auto_flush or (self._flush_task is not None and not self._flush_task.done()):
            return
        try:
            self._flush_task = asyncio.get_running_loop().create_task(self._delayed_flush(delay))
        except RuntimeError:  # no running loop: the next event flushes instead
            self._flush_task = None

    async def _delayed_flush(self, delay: float) -> None:
        await self.sleeper(delay)
        self._flush_task = None
        try:
            await self.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("early-bird delayed flush failed: %s", type(exc).__name__)

    async def _send(self, kind: str, text: str) -> bool:
        now = self.clock()
        if self.day != now.date():
            self.day, self.sent_today = now.date(), 0
        if self.client is None or self.chat_id is None or self.sent_today >= DAILY_CAP:
            self.dropped += 1
            return False
        try:
            await self.client.send_message(self.chat_id, text)
        except Exception as exc:  # noqa: BLE001 - Telegram down: drop, never raise into the bus
            logger.info("early-bird send failed: %s", type(exc).__name__)
            return False
        self.sent_today += 1
        self.last_sent[kind] = now
        return True

    async def close(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._flush_task


def register(bus: Any, notifier: EarlyBirdNotifier) -> list[str]:
    """Subscribe the notifier; topics the bus does not know yet are skipped (logged), never raised."""
    subscribed = []
    for topic in TOPICS:
        try:
            bus.subscribe(topic, notifier.handle)
        except Exception as exc:  # noqa: BLE001 - e.g. ValueError("unknown_topic:...") before the bus lists it
            logger.info("early-bird notifier cannot subscribe to %s: %s", topic, exc)
            continue
        subscribed.append(topic)
    return subscribed
