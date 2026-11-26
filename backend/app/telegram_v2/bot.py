"""Owner-only Telegram HITL bot: getUpdates long polling + outbound HITL dispatcher.

Runs as an asyncio task inside the 24/7 worker (or standalone via the CLI).
Never blocks the application loop:

- Unauthorized chats/users are ignored entirely (no reply).
- HTTP 409 (another poller, e.g. the legacy com.automated-apply.rust agent)
  sets polling_state='conflict' and backs off quietly (default 60 s).
- `last_update_id` is persisted after every update so restarts never replay
  an old owner command.
- OPEN hitl_requests without telegram_msg_id are sent (<= 1 msg/s) and the
  message id is saved immediately so a restart never double-sends.

Inbound matching order: inline button callback -> slash command (/ask <text> goes to
the control agent) -> swipe-reply (reply_to_message.message_id == telegram_msg_id) ->
plain text that resolves the ONLY open QUESTION/OTP (when it is not clearly a control
command) -> Phase 6A LangGraph control agent (free chat). The agent runs as a background
task: polling continues and the browser's in-flight application is never touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from backend.app.browser_v2.hitl import HITLResolutionService, PortalResume, Resolution
from backend.app.browser_v2.store import HitlRecord, Store, WorkerState
from backend.app.telegram_v2.client import (
    TelegramBadRequest,
    TelegramClient,
    TelegramConflict,
    TelegramError,
    TelegramRateLimited,
    TelegramUnauthorized,
    redact,
)
from backend.app.telegram_v2.config import TelegramConfig
from backend.app.telegram_v2.formatting import (
    CONFLICT_MESSAGE,
    HELP_TEXT,
    render_hitl,
    render_pending,
    render_resolved,
    render_status,
)

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SEC = 25
DISPATCH_INTERVAL_SEC = 5.0
CONFLICT_BACKOFF_SEC = 60.0
UNAUTHORIZED_BACKOFF_SEC = 300.0
MAX_ERROR_BACKOFF_SEC = 60.0
PLAIN_TEXT_KINDS = frozenset({"QUESTION", "OTP"})
MAX_PENDING_LISTED = 20


class TelegramBot:
    def __init__(self, config: TelegramConfig, store: Store, *, cache: Any = None,
                 ai: AIRuntime | None = None, client: TelegramClient | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], datetime] | None = None,
                 poll_timeout: int = POLL_TIMEOUT_SEC, dispatch_interval: float = DISPATCH_INTERVAL_SEC,
                 conflict_backoff: float = CONFLICT_BACKOFF_SEC, min_send_interval: float = 1.0,
                 agent: Any = None, event_bus: Any = None, mail_events: Any = None) -> None:
        self.config = config
        self.store = store
        self.ai = ai
        self.event_bus = event_bus
        self.mail_events = mail_events
        self._agent = agent
        self._agent_tasks: set[asyncio.Task[None]] = set()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.resolver = HITLResolutionService(store, cache if cache is not None else (ai.cache if ai else None),
                                              clock=self.clock)
        self.client = client
        if self.client is None and config.configured and config.token:
            self.client = TelegramClient(config.token, transport=transport, min_send_interval=min_send_interval)
        self.poll_timeout = poll_timeout
        self.dispatch_interval = dispatch_interval
        self.conflict_backoff = conflict_backoff
        self._offset_loaded = False
        self._last_update_id: int | None = None
        self._state: str | None = None
        self._failures = 0

    @property
    def chat_id(self) -> int:
        assert self.config.owner_chat_id is not None
        return self.config.owner_chat_id

    # --- lifecycle -----------------------------------------------------------------
    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll + dispatch until stop_event; never raises into the worker loop."""
        if not self.config.configured or self.client is None:
            await self._set_state("unconfigured", last_error=self.config.problem)
            logger.info("telegram_v2 unconfigured (%s); worker continues without Telegram", self.config.problem)
            return
        await self._set_state("starting", last_error=None)
        tasks = [asyncio.create_task(self._poll_loop(stop_event), name="telegram-poll"),
                 asyncio.create_task(self._dispatch_loop(stop_event), name="telegram-dispatch")]
        stopper = asyncio.create_task(stop_event.wait())
        try:
            await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (*tasks, stopper, *self._agent_tasks):
                task.cancel()
            await asyncio.gather(*tasks, stopper, *self._agent_tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self._set_state("stopped")
            await self.client.aclose()

    async def _wait(self, stop_event: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, seconds))

    async def _poll_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            delay = await self.poll_once()
            if delay:
                await self._wait(stop_event, delay)

    async def _dispatch_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.dispatch_once()
            except Exception as exc:  # noqa: BLE001 - keep dispatching on the next tick
                logger.warning("telegram_v2 dispatch failed: %s", redact(type(exc).__name__))
            await self._wait(stop_event, self.dispatch_interval)

    async def _set_state(self, polling_state: str, **changes: Any) -> None:
        self._state = polling_state
        await self.store.update_telegram_state(polling_state=polling_state, **changes)

    # --- inbound -------------------------------------------------------------------
    async def poll_once(self) -> float:
        """One getUpdates round. Returns seconds to back off (0 = poll again now)."""
        assert self.client is not None
        if not self._offset_loaded:
            self._last_update_id = (await self.store.get_telegram_state()).last_update_id
            self._offset_loaded = True
        offset = self._last_update_id + 1 if self._last_update_id is not None else None
        try:
            updates = await self.client.get_updates(offset, timeout=self.poll_timeout)
        except TelegramConflict:
            if self._state != "conflict":
                logger.warning("telegram_v2 409 conflict: %s; backing off %ss", CONFLICT_MESSAGE,
                               int(self.conflict_backoff))
            await self._set_state("conflict", conflict_detected_at=self.clock(), last_error=CONFLICT_MESSAGE)
            return self.conflict_backoff
        except TelegramRateLimited as exc:
            await self._set_state("error", last_error="rate_limited by Telegram")
            return exc.retry_after
        except TelegramUnauthorized:
            await self._set_state("error", last_error="bot token rejected by Telegram (check TELEGRAM_BOT_TOKEN)")
            return UNAUTHORIZED_BACKOFF_SEC
        except TelegramError as exc:
            self._failures += 1
            await self._set_state("error", last_error=exc.code)
            return min(MAX_ERROR_BACKOFF_SEC, 2.0 ** min(self._failures, 6))
        except Exception as exc:  # noqa: BLE001 - e.g. DB hiccup; never kill the poller
            self._failures += 1
            logger.warning("telegram_v2 poll failed: %s", type(exc).__name__)
            return min(MAX_ERROR_BACKOFF_SEC, 2.0 ** min(self._failures, 6))
        self._failures = 0
        await self._set_state("polling", last_poll_at=self.clock(), last_error=None)
        for update in updates:
            update_id = update["update_id"]
            if self._last_update_id is not None and update_id <= self._last_update_id:
                continue
            try:
                await self.handle_update(update)
            except Exception as exc:  # noqa: BLE001 - a poison update must not be retried forever
                logger.warning("telegram_v2 update %s failed: %s", update_id, redact(type(exc).__name__))
            finally:
                self._last_update_id = update_id
                await self.store.update_telegram_state(last_update_id=update_id)
        return 0.0

    def authorized(self, chat_id: Any, user_id: Any) -> bool:
        if chat_id is None or chat_id != self.config.owner_chat_id:
            return False
        return self.config.owner_user_id is None or user_id == self.config.owner_user_id

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            message = callback.get("message") or {}
            if not self.authorized((message.get("chat") or {}).get("id"), (callback.get("from") or {}).get("id")):
                logger.warning("telegram_v2 ignored callback from an unauthorized chat")
                return
            await self.handle_callback(callback)
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        if not self.authorized((message.get("chat") or {}).get("id"), (message.get("from") or {}).get("id")):
            logger.warning("telegram_v2 ignored message from an unauthorized chat")
            return
        text = (message.get("text") or "").strip()
        message_id = message.get("message_id")
        if text.startswith("/"):
            head = text.split(maxsplit=1)[0].split("@")[0].lower()
            if head == "/ask":
                self.dispatch_agent(text[len(text.split(maxsplit=1)[0]):].strip(), message_id)
                return
            await self.reply(await self.handle_command(text), message_id)
            return
        reply_to = message.get("reply_to_message")
        if isinstance(reply_to, dict) and reply_to.get("message_id") is not None:
            hitl = await self.store.find_hitl_by_message(reply_to["message_id"])
            if hitl is not None:
                await self.reply(await self.handle_reply(hitl, text), message_id)
                return
        await self.route_plain(text, message_id)

    # --- Phase 6A: free chat -> LangGraph control agent (non-blocking) -------------------------
    @property
    def agent(self) -> Any:
        if self._agent is None:
            from backend.app.agent_v2.control_graph import ControlAgent

            self._agent = ControlAgent(self.store, ai=self.ai, mail_events=self.mail_events,
                                       event_bus=self.event_bus, clock=self.clock)
        return self._agent

    @staticmethod
    def is_control_command(text: str) -> bool:
        from backend.app.agent_v2.intent import parse

        intent = parse(text)
        return intent is not None and intent.tool != "help"

    async def route_plain(self, text: str, message_id: int | None) -> None:
        if not text:
            await self.reply("Send the answer as text. /help", message_id)
            return
        rows, _ = await self.store.list_hitl("OPEN", limit=50)
        candidates = [row for row in rows if row.kind in PLAIN_TEXT_KINDS]
        command = self.is_control_command(text)
        if len(candidates) == 1 and not command:
            await self.reply(await self.handle_plain(text), message_id)
            return
        hint = None
        if len(candidates) > 1 and not command:
            hint = await self.handle_plain(text)  # "N questions are open, so I won't guess" + refs
        self.dispatch_agent(text, message_id, fallback=hint)

    def dispatch_agent(self, text: str, message_id: int | None, *, fallback: str | None = None) -> asyncio.Task[None]:
        task = asyncio.create_task(self._agent_reply(text, message_id, fallback), name="telegram-agent")
        self._agent_tasks.add(task)
        task.add_done_callback(self._agent_tasks.discard)
        return task

    async def _agent_reply(self, text: str, message_id: int | None, fallback: str | None) -> None:
        try:
            if not text.strip():
                await self.reply("Usage: <code>/ask &lt;text&gt;</code>", message_id)
                return
            result = await self.agent.run(text)
            if fallback is not None and result.get("verdict") == "help":
                await self.reply(fallback, message_id)
                return
            await self.reply("🤖 " + html.escape(str(result.get("reply") or ""), quote=False), message_id)
        except Exception as exc:  # noqa: BLE001 - the agent must never break polling
            logger.warning("telegram_v2 agent failed: %s", type(exc).__name__)
            with contextlib.suppress(Exception):
                await self.reply("⚠️ The control agent hit an error; nothing was changed.", message_id)

    async def drain_agent(self) -> None:
        if self._agent_tasks:
            await asyncio.gather(*list(self._agent_tasks), return_exceptions=True)

    async def reply(self, text: str, reply_to: int | None = None) -> None:
        assert self.client is not None
        await self.client.send_message(self.chat_id, text, reply_to=reply_to)

    # --- callbacks ------------------------------------------------------------------
    async def handle_callback(self, callback: dict[str, Any]) -> None:
        assert self.client is not None
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        message_id = message.get("message_id")
        action, _, rest = data.partition(":")
        notice = "Done."
        if action == "resume":
            outcome = await self.resolver.resume_portal(rest, via="telegram")
            notice = outcome.message
            await self._close_messages(outcome)
        elif action in {"ans", "skip", "retry"}:
            ref, _, index = rest.partition(":")
            hitl = await self.store.find_hitl_by_message(message_id) if message_id is not None else None
            if hitl is None or hitl.ref != ref:
                hitl, problem = await self.resolver.by_ref(ref)
                if problem is not None:
                    hitl = None
            if hitl is None:
                notice = "That request no longer exists."
            elif hitl.status != "OPEN":
                notice = f"Already {hitl.status.lower()} — nothing changed."
                await self._edit(hitl, f"Already {hitl.status.lower()}"
                                 + (f": {hitl.answer_text}" if hitl.answer_text and hitl.kind == "QUESTION" else ""))
            else:
                if action == "ans" and index.isdigit():
                    result = await self.resolver.answer_option(hitl.id, int(index), via="telegram")
                elif action == "skip":
                    result = await self.resolver.skip(hitl.id, via="telegram")
                elif action == "retry":
                    result = await self.resolver.retry(hitl.id, via="telegram")
                else:
                    result = Resolution(False, "invalid_option", "Unknown button.")
                notice = result.message
                await self._after_resolution(result)
        else:
            notice = "Unknown button."
        try:
            await self.client.answer_callback_query(str(callback.get("id") or ""), notice)
        except TelegramError as exc:
            logger.warning("telegram_v2 answerCallbackQuery failed: %s", exc.code)

    # --- commands -------------------------------------------------------------------
    async def handle_command(self, text: str) -> str:
        head, _, argument = text.partition(" ")
        command, _, _mention = head.partition("@")
        command, argument = command.lower(), argument.strip()
        if command in {"/help", "/start"}:
            return HELP_TEXT
        if command == "/status":
            return await self.status_text()
        if command == "/pending":
            rows, total = await self.store.list_hitl("OPEN", limit=MAX_PENDING_LISTED)
            return render_pending(rows, total)
        if command == "/pause":
            control = await self.store.set_worker_control(WorkerState.PAUSED)
            return f"⏸ Worker desired state: <b>{control.desired_state.value}</b> (takes effect between jobs)."
        if command in {"/start_worker", "/unpause"}:
            control = await self.store.set_worker_control(WorkerState.RUNNING)
            mode = "DRY RUN" if control.dry_run else "LIVE"
            return f"▶️ Worker desired state: <b>{control.desired_state.value}</b> ({mode})."
        if command == "/resume":
            if not argument:
                return "Usage: <code>/resume &lt;portal&gt;</code>"
            outcome = await self.resolver.resume_portal(argument.split()[0], via="telegram")
            await self._close_messages(outcome)
            return ("🔓 " if outcome.ok else "") + _html(outcome.message)
        if command in {"/answer", "/once", "/skip", "/retry"}:
            ref, _, answer = argument.partition(" ")
            if not ref:
                return f"Usage: <code>{command} &lt;ref&gt;{' &lt;text&gt;' if command in {'/answer', '/once'} else ''}</code>"
            hitl, problem = await self.resolver.by_ref(ref)
            if problem is not None or hitl is None:
                return _html(problem.message if problem else "Not found.")
            if command == "/skip":
                result = await self.resolver.skip(hitl.id, via="telegram")
            elif command == "/retry":
                result = await self.resolver.retry(hitl.id, via="telegram")
            else:
                if not answer.strip():
                    return f"Usage: <code>{command} {hitl.ref} &lt;text&gt;</code>"
                result = await self.resolver.answer(hitl.id, answer, cache_answer=command == "/answer",
                                                    via="telegram")
            await self._after_resolution(result)
            return _outcome(result)
        return "Unknown command. /help"

    async def handle_reply(self, hitl: HitlRecord, text: str) -> str:
        if hitl.status != "OPEN":
            return f"Request <code>{hitl.ref}</code> is already {hitl.status.lower()} — nothing changed."
        if hitl.kind == "AUTH":
            outcome = await self.resolver.resume_portal(hitl.platform, via="telegram")
            await self._close_messages(outcome)
            return "🔓 " + _html(outcome.message)
        if hitl.kind == "ERROR":
            lowered = text.lower()
            if lowered in {"retry", "skip"}:
                result = await (self.resolver.retry if lowered == "retry" else self.resolver.skip)(
                    hitl.id, via="telegram")
                await self._after_resolution(result)
                return _outcome(result)
            return f"Reply <b>retry</b> or <b>skip</b>, or use <code>/retry {hitl.ref}</code>."
        if not text:
            return "Send the answer as text."
        result = await self.resolver.answer(hitl.id, text, cache_answer=True, via="telegram")
        await self._after_resolution(result)
        return _outcome(result)

    async def handle_plain(self, text: str) -> str:
        if not text:
            return "Send the answer as text. /help"
        rows, _ = await self.store.list_hitl("OPEN", limit=50)
        candidates = [row for row in rows if row.kind in PLAIN_TEXT_KINDS]
        if not candidates:
            return "Nothing is waiting for an answer. /pending · /help"
        if len(candidates) > 1:
            refs = ", ".join(f"<code>{row.ref}</code>" for row in candidates[:10])
            return (f"{len(candidates)} questions are open, so I won't guess. Swipe-reply to the specific "
                    f"message or use <code>/answer &lt;ref&gt; &lt;text&gt;</code>. Refs: {refs}")
        result = await self.resolver.answer(candidates[0].id, text, cache_answer=True, via="telegram")
        await self._after_resolution(result)
        return _outcome(result)

    async def status_text(self) -> str:
        from backend.app.browser_v2.service import quota_counts

        now = self.clock()
        portals = []
        for rules in await self.store.list_rules():
            counts = await quota_counts(self.store, rules, now)
            portals.append({"platform": rules.platform, "enabled": rules.enabled,
                            "auto_apply_enabled": rules.auto_apply_enabled, "auth_status": rules.auth_status,
                            "applied_today": counts["applied_today"],
                            "max_applies_per_day": rules.max_applies_per_day})
        providers = None
        if self.ai is not None:
            providers = [p["provider"] for p in await self.ai.router.status() if p["status"] != "unconfigured"]
        telegram = (await self.store.get_telegram_state()).polling_state
        return render_status(worker=await self.store.get_worker_control(), portals=portals,
                             open_hitl=await self.store.count_open_hitl(), providers=providers,
                             telegram_state=telegram, now=now)

    # --- outbound -------------------------------------------------------------------
    async def dispatch_once(self, limit: int = 10) -> int:
        """Send undelivered OPEN requests; persist telegram_msg_id right after each send."""
        assert self.client is not None
        sent = 0
        for hitl in await self.store.undelivered_hitl(limit):
            text, markup = render_hitl(hitl)
            try:
                message = await self.client.send_message(self.chat_id, text, reply_markup=markup)
            except TelegramRateLimited as exc:
                logger.info("telegram_v2 dispatch rate limited; retry in %ss", exc.retry_after)
                break
            except TelegramError as exc:
                logger.warning("telegram_v2 dispatch of %s failed: %s", hitl.ref, exc.code)
                break
            message_id = (message or {}).get("message_id")
            if isinstance(message_id, int):
                await self.store.mark_hitl_delivered(hitl.id, message_id)
                sent += 1
        return sent

    async def send_test_ping(self) -> dict[str, Any]:
        assert self.client is not None
        message = await self.client.send_message(
            self.chat_id, "✅ automated-apply v2: Telegram HITL bot can reach you. Send /help for commands.")
        return {"sent": True, "message_id": (message or {}).get("message_id")}

    # --- message edits after resolution -----------------------------------------------
    async def _after_resolution(self, result: Resolution) -> None:
        if result.ok and result.hitl is not None and self.event_bus is not None:
            with contextlib.suppress(Exception):
                await self.event_bus.publish("hitl.resolved", {"ref": result.hitl.ref, "kind": result.hitl.kind,
                                                               "platform": result.hitl.platform,
                                                               "outcome": result.code})
        if result.ok and result.hitl is not None:
            if result.code == "answered":
                label = f"Answered: {result.answer}" if result.hitl.kind == "QUESTION" else "Answered"
                if result.cached:
                    label += " (saved to cache)"
            else:
                label = {"skipped": "Skipped", "retried": "Retrying"}.get(result.code, result.code)
            await self._edit(result.hitl, label)

    async def _close_messages(self, outcome: PortalResume) -> None:
        for hitl in outcome.resolved:
            await self._edit(hitl, "Portal resumed")

    async def _edit(self, hitl: HitlRecord, outcome: str) -> None:
        if self.client is None or hitl.telegram_msg_id is None:
            return
        try:
            await self.client.edit_message_text(self.chat_id, hitl.telegram_msg_id, render_resolved(hitl, outcome))
        except TelegramBadRequest:
            pass  # "message is not modified" / too old to edit
        except TelegramError as exc:
            logger.info("telegram_v2 edit of %s failed: %s", hitl.ref, exc.code)


def _html(text: str) -> str:
    from html import escape

    return escape(text)


def _outcome(result: Resolution) -> str:
    return ("✅ " if result.ok else "⚠️ ") + _html(result.message)


async def telegram_status(store: Store, config: TelegramConfig | None = None,
                          now: datetime | None = None) -> dict[str, Any]:
    """Status for the API/CLI/MCP: never includes the token."""
    config = config or TelegramConfig.from_env()
    state = await store.get_telegram_state()
    now = now or datetime.now(UTC)
    polling = state.polling_state if config.configured else "unconfigured"
    stale = bool(config.configured and polling == "polling"
                 and (state.last_poll_at is None or (now - state.last_poll_at).total_seconds() > 120))
    return {"configured": config.configured, "polling_state": polling, "stale": stale,
            "conflict_detected": polling == "conflict",
            "conflict_detected_at": state.conflict_detected_at, "last_poll_at": state.last_poll_at,
            "last_update_id": state.last_update_id,
            "last_error": redact(state.last_error) if state.last_error else (config.problem if not config.configured else None),
            "owner_chat_id": config.masked_chat_id(), "open_hitl_count": await store.count_open_hitl()}
