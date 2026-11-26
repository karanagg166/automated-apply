"""Shared state, constants and logger for the TelegramBot mixins.

`TelegramBot.__init__` (bot.py) assigns every attribute annotated on `TelegramBotBase`;
the mixins (polling, routing, commands, outbound) only read/write them.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.hitl import (
        HITLResolutionService,
        PortalResume,
        Resolution,
    )
    from backend.app.browser_v2.store import HitlRecord, Store
    from backend.app.telegram_v2.client import TelegramClient
    from backend.app.telegram_v2.config import TelegramConfig

# Same logger name as before the mixin split.
logger = logging.getLogger("backend.app.telegram_v2.bot")

POLL_TIMEOUT_SEC = 25
DISPATCH_INTERVAL_SEC = 5.0
CONFLICT_BACKOFF_SEC = 60.0
MAX_CONFLICT_BACKOFF_SEC = 600.0
UNAUTHORIZED_BACKOFF_SEC = 300.0
MAX_ERROR_BACKOFF_SEC = 60.0
PLAIN_TEXT_KINDS = frozenset({"QUESTION", "OTP"})
MAX_PENDING_LISTED = 20
MAX_AGENT_TASKS = 3
LEGACY_AGENT_LABEL = "com.automated-apply.rust"
# Short acknowledgements are never taken as the answer to an open question.
# Phase 9C: bare digits while an OTP request is open resolve it directly (never sent to an LLM).
OTP_CODE = re.compile(r"\d{4,8}")
CHIT_CHAT = re.compile(r"^(?:thanks?(?: you)?|thx|ty|ok(?:ay)?|k|cool|nice|great|hi|hello|hey|yo|"
                       r"good (?:morning|night|evening)|👍|🙏|👌|✅)[.!\s]*$", re.IGNORECASE)


class TelegramBotBase:
    """Attributes set by `TelegramBot.__init__`; cross-mixin methods are declared for type checkers only."""

    config: TelegramConfig
    store: Store
    ai: AIRuntime | None
    event_bus: Any
    mail_events: Any
    _agent: Any
    _agent_tasks: set[asyncio.Task[None]]
    clock: Callable[[], datetime]
    resolver: HITLResolutionService
    client: TelegramClient | None
    poll_timeout: int
    dispatch_interval: float
    conflict_backoff: float
    _offset_loaded: bool
    _last_update_id: int | None
    _state: str | None
    _failures: int
    _conflicts: int
    _conflict_diagnosis: str | None
    legacy_probe: Callable[[], Awaitable[bool | None]]
    agent_wake: Callable[[], Any] | None  # Phase 9C: wakes the worker after an owner priority job
    agent_profile_sync: Any = None  # Phase 9D: ProfileSyncScheduler injected by the worker runtime

    if TYPE_CHECKING:
        @property
        def chat_id(self) -> int: ...

        async def _poll_loop(self, stop_event: asyncio.Event) -> None: ...

        async def dispatch_once(self, limit: int = 10) -> int: ...

        async def handle_command(self, text: str) -> str: ...

        async def reply(self, text: str, reply_to: int | None = None) -> None: ...

        async def _safe_reply(self, text: str, reply_to: int | None = None) -> None: ...

        async def handle_reply(self, hitl: HitlRecord, text: str) -> str: ...

        async def handle_plain(self, text: str) -> str: ...

        async def answerable(self) -> list[HitlRecord]: ...

        async def _after_resolution(self, result: Resolution) -> None: ...

        async def _close_messages(self, outcome: PortalResume) -> None: ...

        async def _edit(self, hitl: HitlRecord, outcome: str, *, icon: str = "✅") -> None: ...
