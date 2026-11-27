"""NotificationRouter: the single outbound gateway for non-HITL Telegram notifications.

Subscribed to the event bus (`notify_policy.TOPICS`); legacy callers use `notify_text`. Every
event is classified (P0..P3, see notify_policy) and then:
  1. dedup/cooldown against the persistent ledger (public.telegram_notification_ledger) -
     a suppressed repeat only bumps `suppressed_count` (shown on the next real alert);
  2. P3 -> log only; P2 -> digest queue (public.telegram_digest_queue), never pushed;
  3. /mute, quiet hours (P0 only breaks them for OTP/CAPTCHA - handled by the HITL dispatcher)
     and the hourly push budget defer P1/P2 into the digest instead of pushing;
  4. P1 -> one silent rollup message per window; P0 -> immediate push.
Pushes go through a bounded priority queue drained by one sender task (P0 first) with bounded
retries; on shutdown pending pushes get `drain_timeout` seconds, the rest land in the digest.
Before followup 007 is applied every store call falls back to process memory (logged once).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import itertools
import logging
from collections import Counter, deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.telegram_v2.notify_policy import (
    TOPICS,
    Notification,
    NotifyConfig,
    Priority,
    classify,
)

logger = logging.getLogger(__name__)
Clock = Callable[[], datetime]
PrefsProvider = Callable[[], Awaitable[Mapping[str, Any]]]
MAX_ROLLUP_LINES = 15


class NotificationRouter:
    def __init__(self, client: Any, chat_id: int | None, store: Any, config: NotifyConfig | None = None, *,
                 clock: Clock | None = None, sleeper: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 prefs_provider: PrefsProvider | None = None, queue_size: int = 100, max_attempts: int = 3,
                 drain_timeout: float = 10.0) -> None:
        self.client, self.chat_id, self.store = client, chat_id, store
        self.config = config or NotifyConfig()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper
        self.prefs_provider = prefs_provider
        self.max_attempts = max_attempts
        self.drain_timeout = drain_timeout
        self.queue: asyncio.PriorityQueue[tuple[int, int, Notification, int]] = asyncio.PriorityQueue(queue_size)
        self.rollup: list[Notification] = []
        self.push_times: deque[datetime] = deque()
        self.stats: Counter[str] = Counter()
        self._seq = itertools.count()
        self._sender: asyncio.Task[None] | None = None
        self._rollup_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._mem_ledger: dict[str, dict[str, Any]] = {}
        self._mem_digest: list[dict[str, Any]] = []
        self._mem_mute: datetime | None = None
        self._degraded_logged = False
        self.closed = False

    # --- bus ----------------------------------------------------------------------------------
    def register(self, bus: Any) -> list[str]:
        subscribed = []
        for topic in TOPICS:
            try:
                bus.subscribe(topic, self.handle)
                subscribed.append(topic)
            except Exception as exc:  # noqa: BLE001 - a topic the bus does not know yet
                logger.info("notification router cannot subscribe to %s: %s", topic, exc)
        return subscribed

    async def handle(self, topic: str, payload: Mapping[str, Any]) -> None:
        """Bus entry point: never raises into the bus."""
        try:
            notification = classify(topic, payload, self.config, self.clock())
            if notification is not None:
                await self.submit(notification)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification %s failed: %s", topic, type(exc).__name__)

    async def notify_text(self, text: str, *, topic: str = "quota.summary", platform: str | None = None) -> None:
        """Legacy `notify(text)` callers (quota summary): routed as routine (P2) digest items."""
        await self.handle(topic, {"text": text, "platform": platform or "system"})

    # --- policy -------------------------------------------------------------------------------
    async def submit(self, n: Notification) -> str:
        now = self.clock()
        self.stats[f"p{int(n.priority)}"] += 1
        if n.resolves:
            await self._resolve(n.resolves, n, now)
            return "resolved"
        if n.priority == Priority.P3:
            logger.info("notify P3 %s: %s", n.topic, n.digest_line[:200])
            return "logged"
        if n.priority == Priority.P1 and n.topic.startswith("job.") and not await self._early_bird_enabled():
            n = Notification(n.topic, Priority.P2, n.text, n.digest_line, n.dedup_key, n.cooldown)
        async with self._lock:
            if n.dedup_key and n.cooldown and await self._in_cooldown(n, now):
                self.stats["suppressed"] += 1
                await self._ledger_record(n, now, sent=False, suppressed=True)
                return "suppressed"
            if n.priority == Priority.P2:
                await self._to_digest(n)
                await self._ledger_record(n, now, sent=False)
                return "digest"
            hold = await self._hold_reason(n, now)
            if hold is not None:
                self.stats[f"deferred_{hold}"] += 1
                await self._to_digest(n, hold)
                await self._ledger_record(n, now, sent=False)
                return f"deferred:{hold}"
            await self._ledger_record(n, now, sent=True)
            if n.priority == Priority.P1:
                self.rollup.append(n)
                self._schedule_rollup()
                return "rollup"
        await self._enqueue(n)
        return "push"

    async def _hold_reason(self, n: Notification, now: datetime) -> str | None:
        if n.priority > Priority.P0 and (muted := await self.muted_until()) is not None and muted > now:
            return "muted"
        if self.config.in_quiet(now) and (n.priority > Priority.P0 or not self.config.quiet_hitl_override):
            return "quiet_hours"
        if n.priority > Priority.P0 and not self.budget_ok(now):
            return "hourly_budget"
        return None

    def budget_ok(self, now: datetime) -> bool:
        while self.push_times and now - self.push_times[0] > timedelta(hours=1):
            self.push_times.popleft()
        return len(self.push_times) < self.config.max_pushes_per_hour

    async def _in_cooldown(self, n: Notification, now: datetime) -> bool:
        entry = await self._ledger_get(n.dedup_key or "")
        if entry is None:
            return False
        ref = entry.get("last_sent_at") or (entry.get("last_event_at") if n.priority == Priority.P2 else None)
        return ref is not None and n.cooldown is not None and now - ref < n.cooldown

    async def _early_bird_enabled(self) -> bool:
        if self.prefs_provider is None:
            return True
        try:
            prefs = await self.prefs_provider()
        except Exception:  # noqa: BLE001 - unreadable profile: keep the default (on)
            return True
        return (prefs or {}).get("notify_early_bird") is not False

    # --- rollup + push queue ------------------------------------------------------------------
    def _schedule_rollup(self) -> None:
        if self._rollup_task is None or self._rollup_task.done():
            self._rollup_task = asyncio.get_running_loop().create_task(self._delayed_rollup())

    async def _delayed_rollup(self) -> None:
        await self.sleeper(self.config.rollup.total_seconds())
        await self.flush_rollup()

    async def flush_rollup(self) -> int:
        batch, self.rollup = self.rollup[:], []
        if not batch:
            return 0
        if len(batch) == 1:
            text = batch[0].text
        else:
            lines = [f"🔔 <b>{len(batch)} updates</b>"] + [f"• {n.text}" for n in batch[:MAX_ROLLUP_LINES]]
            if len(batch) > MAX_ROLLUP_LINES:
                lines.append(f"… and {len(batch) - MAX_ROLLUP_LINES} more in the next digest")
                for n in batch[MAX_ROLLUP_LINES:]:
                    await self._to_digest(n)
            text = "\n".join(lines)
        hold = await self._hold_reason(batch[0], self.clock())
        if hold is not None:
            for n in batch:
                await self._to_digest(n, hold)
            return 0
        await self._enqueue(Notification("rollup", Priority.P1, text, "rollup"))
        return len(batch)

    async def _enqueue(self, n: Notification, attempts: int = 0) -> None:
        if self.closed:
            await self._to_digest(n, "shutdown")
            return
        try:
            self.queue.put_nowait((int(n.priority), next(self._seq), n, attempts))
        except asyncio.QueueFull:
            self.stats["queue_full"] += 1
            logger.error("telegram outbound queue full: %s deferred to the digest", n.topic)
            await self._to_digest(n, "queue_full")
            return
        if self._sender is None or self._sender.done():
            self._sender = asyncio.get_running_loop().create_task(self._send_loop(), name="telegram-notify")

    async def _send_loop(self) -> None:
        while True:
            _, _, n, attempts = await self.queue.get()
            try:
                await self._deliver(n, attempts)
            finally:
                self.queue.task_done()

    async def _deliver(self, n: Notification, attempts: int) -> None:
        if self.client is None or self.chat_id is None:
            await self._to_digest(n, "telegram_unconfigured")
            return
        try:
            message = await self.client.send_message(self.chat_id, n.text, silent=n.priority >= Priority.P1)
        except Exception as exc:  # noqa: BLE001 - classified below; never raise out of the sender
            from backend.app.telegram_v2.client import (
                TelegramBadRequest,
                TelegramUnauthorized,
            )

            permanent = isinstance(exc, (TelegramUnauthorized, TelegramBadRequest))
            if permanent or attempts + 1 >= self.max_attempts:
                self.stats["dead_letter"] += 1
                logger.error("telegram notification %s dead-lettered after %d attempt(s): %s", n.topic,
                             attempts + 1, getattr(exc, "code", type(exc).__name__))
                await self._to_digest(n, "undelivered")
                return
            await self.sleeper(min(60.0, 2.0 ** attempts))
            await self._enqueue(n, attempts + 1)
            return
        self.stats["pushed"] += 1
        if n.priority > Priority.P0:
            self.push_times.append(self.clock())
        message_id = (message or {}).get("message_id") if isinstance(message, dict) else None
        if n.dedup_key and isinstance(message_id, int):
            await self._ledger_record(n, self.clock(), sent=True, message_id=message_id)

    async def _resolve(self, key: str, n: Notification, now: datetime) -> None:
        entry = await self._ledger_get(key)
        await self._to_digest(n)
        if entry is None or entry.get("resolved_at") is not None:
            return
        await self._store_call("ledger_resolve", key, now)
        self._mem_ledger.setdefault(key, {})["resolved_at"] = now
        message_id = entry.get("message_id")
        if self.client is not None and self.chat_id is not None and isinstance(message_id, int):
            with contextlib.suppress(Exception):  # card already gone / not modified: nothing to do
                await self.client.edit_message_text(self.chat_id, message_id,
                                                    f"🟢 <s>{html.escape(entry.get('topic') or '')}</s> "
                                                    f"{html.escape(n.digest_line)}")

    # --- ledger API for the HITL dispatcher (AUTH card cooldown) ------------------------------
    async def recently_sent(self, key: str, cooldown: timedelta, now: datetime) -> bool:
        entry = await self._ledger_get(key)
        last = (entry or {}).get("last_sent_at")
        return last is not None and now - last < cooldown

    async def mark_sent(self, key: str, topic: str, priority: int, message_id: int | None = None) -> None:
        n = Notification(topic, Priority(priority), "", "", key)
        await self._ledger_record(n, self.clock(), sent=True, message_id=message_id)

    # --- persistence (store, falling back to memory before followup 007) ----------------------
    async def _store_call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.store, name, None)
        if method is None:
            return None
        try:
            return await method(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - e.g. UndefinedTable before followup 007
            if not self._degraded_logged:
                self._degraded_logged = True
                logger.warning("notification store unavailable (%s); using process memory - apply followup 007",
                               type(exc).__name__)
            raise _Degraded() from None

    async def _ledger_get(self, key: str) -> dict[str, Any] | None:
        try:
            entry = await self._store_call("ledger_get", key)
            return vars(entry) if entry is not None else None
        except _Degraded:
            return self._mem_ledger.get(key)

    async def _ledger_record(self, n: Notification, now: datetime, *, sent: bool, suppressed: bool = False,
                             message_id: int | None = None) -> None:
        if not n.dedup_key:
            return
        try:
            await self._store_call("ledger_record", n.dedup_key, topic=n.topic, priority=int(n.priority), now=now,
                                   sent=sent, suppressed=suppressed, chat_id=self.chat_id, message_id=message_id)
        except _Degraded:
            entry = self._mem_ledger.setdefault(n.dedup_key, {"topic": n.topic, "suppressed_count": 0})
            entry["last_event_at"] = now
            if sent:
                entry.update(last_sent_at=now, suppressed_count=0, message_id=message_id, resolved_at=None)
            elif suppressed:
                entry["suppressed_count"] = entry.get("suppressed_count", 0) + 1

    async def _to_digest(self, n: Notification, reason: str | None = None) -> None:
        line = n.digest_line + (f" (held: {reason.replace('_', ' ')})" if reason else "")
        try:
            await self._store_call("digest_enqueue", n.topic if n.topic != "rollup" else "system.rollup",
                                   int(n.priority), line, n.dedup_key)
        except _Degraded:
            self._mem_digest.append({"id": f"mem-{next(self._seq)}", "text": line, "priority": int(n.priority)})

    async def pending_digest(self) -> list[Any]:
        try:
            stored = list(await self._store_call("digest_pending") or [])
        except _Degraded:
            stored = []
        return stored + [_MemItem(**row) for row in self._mem_digest]

    async def mark_digest_delivered(self, items: list[Any]) -> None:
        ids = [str(getattr(item, "id", "")) for item in items]
        self._mem_digest = [row for row in self._mem_digest if row["id"] not in ids]
        with contextlib.suppress(_Degraded):
            await self._store_call("digest_mark_delivered", [i for i in ids if not i.startswith("mem-")], self.clock())

    async def muted_until(self) -> datetime | None:
        try:
            state = await self._store_call("get_telegram_state")
            return getattr(state, "muted_until", None) or self._mem_mute
        except _Degraded:
            return self._mem_mute

    async def set_mute(self, until: datetime | None) -> None:
        self._mem_mute = until
        with contextlib.suppress(_Degraded, ValueError):
            await self._store_call("update_telegram_state", muted_until=until)

    def health(self) -> dict[str, Any]:
        return {"queued": self.queue.qsize(), "rollup": len(self.rollup), "pushes_last_hour": len(self.push_times),
                "budget": self.config.max_pushes_per_hour, "stats": dict(self.stats),
                "client_rate_limited": getattr(self.client, "rate_limited", 0),
                "client_circuit_open": bool(getattr(self.client, "circuit_open", False))}

    async def close(self) -> None:
        """Rollup -> digest; pending pushes get `drain_timeout` seconds; the rest -> digest."""
        if self._rollup_task is not None:
            self._rollup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._rollup_task
        for n in self.rollup:
            await self._to_digest(n, "shutdown")
        self.rollup = []
        if self._sender is not None and not self._sender.done():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.queue.join(), timeout=self.drain_timeout)
            self._sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._sender
        self.closed = True
        while not self.queue.empty():
            _, _, n, _ = self.queue.get_nowait()
            await self._to_digest(n, "shutdown")


class _Degraded(Exception):
    pass


class _MemItem:
    def __init__(self, id: str, text: str, priority: int) -> None:  # noqa: A002 - mirrors DigestItem.id
        self.id, self.text, self.priority = id, text, priority
