"""Owner-only Telegram HITL bot: getUpdates long polling + outbound HITL dispatcher.

Runs as an asyncio task inside the 24/7 worker (or standalone via the CLI).
Never blocks the application loop:

- Unauthorized chats/users are ignored entirely (no reply).
- HTTP 409 (another poller, e.g. the legacy com.automated-apply.rust agent, or a
  webhook) sets polling_state='conflict' and backs off exponentially (60 s .. 10 min),
  logging once per episode whether the legacy launchd agent is still loaded or a
  webhook is set. The poll loop is supervised: no exception ever ends it.
- `last_update_id` is persisted after every update so restarts never replay
  an old owner command.
- OPEN hitl_requests without telegram_msg_id are sent (<= 1 msg/s) and the
  message id is saved immediately so a restart never double-sends.

Inbound matching order (Phase 9C, LLM-first): inline button callback (HITL answers, portal
resume, agent Confirm/Cancel) -> slash command (/ask <text> goes to the agent, /forget clears
its memory) -> swipe-reply (reply_to_message.message_id == telegram_msg_id) -> bare digits
while an OTP request is open -> everything else to the LLM agent (agent_v2.react; open HITL
items are in its context so it can resolve them; deterministic fallback when no provider
answers). The agent runs as a background task (<= 3 at once): polling continues and the
browser's in-flight application is never touched. Every callback query is answered
(try/finally), so a button never spins forever.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from backend.app.browser_v2.hitl import HITLResolutionService
from backend.app.browser_v2.store import Store
from backend.app.telegram_v2.base import (
    CHIT_CHAT,
    CONFLICT_BACKOFF_SEC,
    DISPATCH_INTERVAL_SEC,
    LEGACY_AGENT_LABEL,
    MAX_AGENT_TASKS,
    MAX_CONFLICT_BACKOFF_SEC,
    MAX_ERROR_BACKOFF_SEC,
    MAX_PENDING_LISTED,
    PLAIN_TEXT_KINDS,
    POLL_TIMEOUT_SEC,
    UNAUTHORIZED_BACKOFF_SEC,
    logger,
)
from backend.app.telegram_v2.client import (
    TelegramClient,
    TelegramConflict,
    TelegramError,
    TelegramRateLimited,
    TelegramUnauthorized,
    redact,
)
from backend.app.telegram_v2.commands import CommandsMixin
from backend.app.telegram_v2.config import TelegramConfig
from backend.app.telegram_v2.outbound import OutboundMixin, _html, _outcome
from backend.app.telegram_v2.polling import PollingMixin
from backend.app.telegram_v2.routing import RoutingMixin

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime

__all__ = [
    "CHIT_CHAT",
    "CONFLICT_BACKOFF_SEC",
    "DISPATCH_INTERVAL_SEC",
    "LEGACY_AGENT_LABEL",
    "MAX_AGENT_TASKS",
    "MAX_CONFLICT_BACKOFF_SEC",
    "MAX_ERROR_BACKOFF_SEC",
    "MAX_PENDING_LISTED",
    "PLAIN_TEXT_KINDS",
    "POLL_TIMEOUT_SEC",
    "UNAUTHORIZED_BACKOFF_SEC",
    "TelegramBot",
    "_html",
    "_outcome",
    "legacy_poller_loaded",
    "logger",
    "telegram_status",
]


async def legacy_poller_loaded(label: str = LEGACY_AGENT_LABEL) -> bool | None:
    """Read-only `launchctl list <label>`: True when the legacy agent is loaded, None if unknown."""
    launchctl = shutil.which("launchctl")
    if launchctl is None:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            launchctl, "list", label, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(process.wait(), timeout=5) == 0
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


class TelegramBot(PollingMixin, RoutingMixin, CommandsMixin, OutboundMixin):
    def __init__(self, config: TelegramConfig, store: Store, *, cache: Any = None,
                 ai: AIRuntime | None = None, client: TelegramClient | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], datetime] | None = None,
                 poll_timeout: int = POLL_TIMEOUT_SEC, dispatch_interval: float = DISPATCH_INTERVAL_SEC,
                 conflict_backoff: float = CONFLICT_BACKOFF_SEC, min_send_interval: float = 1.0,
                 agent: Any = None, event_bus: Any = None, mail_events: Any = None,
                 legacy_probe: Callable[[], Awaitable[bool | None]] | None = None,
                 agent_wake: Callable[[], Any] | None = None, notifier: Any = None,
                 notify_config: Any = None) -> None:
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
        self.owns_client = client is None  # a shared (worker) client is closed by its owner
        if self.client is None and config.configured and config.token:
            self.client = TelegramClient(config.token, transport=transport, min_send_interval=min_send_interval)
        self.notifier = notifier  # NotificationRouter (/mute, /digest, /health); None in CLI mode
        from backend.app.telegram_v2.notify_policy import NotifyConfig

        self.notify_config = notify_config or getattr(notifier, "config", None) or NotifyConfig(
            quiet_start=None, quiet_end=None)
        self.poll_timeout = poll_timeout
        self.dispatch_interval = dispatch_interval
        self.conflict_backoff = conflict_backoff
        self._offset_loaded = False
        self._last_update_id: int | None = None
        self._state: str | None = None
        self._failures = 0
        self._conflicts = 0
        self._conflict_diagnosis: str | None = None
        self.legacy_probe = legacy_probe or legacy_poller_loaded
        self.agent_wake = agent_wake

    @property
    def chat_id(self) -> int:
        assert self.config.owner_chat_id is not None
        return self.config.owner_chat_id

    # _poll_loop and poll_once stay here: they read the backoff constants as globals of THIS module
    # (tests patch `telegram_v2.bot.MAX_ERROR_BACKOFF_SEC`).
    async def _poll_loop(self, stop_event: asyncio.Event) -> None:
        """Supervised: a DB hiccup or an unexpected error backs off, it never ends polling."""
        while not stop_event.is_set():
            try:
                delay = await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - e.g. telegram_v2_state write failed after sleep/wake
                self._failures += 1
                delay = min(MAX_ERROR_BACKOFF_SEC, 2.0 ** min(self._failures, 6))
                logger.warning("telegram_v2 poll loop error %s; retry in %ss", type(exc).__name__, int(delay))
            if delay:
                await self._wait(stop_event, delay)
            else:
                await asyncio.sleep(0)  # an instant getUpdates must never starve the worker loop

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
            self._conflicts += 1
            delay = min(MAX_CONFLICT_BACKOFF_SEC, self.conflict_backoff * 2 ** min(self._conflicts - 1, 8))
            if self._state != "conflict" or self._conflict_diagnosis is None:
                self._conflict_diagnosis = await self.diagnose_conflict()
                logger.warning("telegram_v2 %s; backing off %ss", self._conflict_diagnosis, int(delay))
            await self._set_state("conflict", conflict_detected_at=self.clock(), last_error=self._conflict_diagnosis)
            return delay
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
        self._conflicts, self._conflict_diagnosis = 0, None
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
