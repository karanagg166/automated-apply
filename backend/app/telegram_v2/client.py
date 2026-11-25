"""Minimal async Telegram Bot API client (httpx) with token redaction.

- The token only ever appears in the request path; exceptions carry a short
  code (never the URL), and httpx/httpcore log records are redacted.
- HTTP 409 (another getUpdates poller or a webhook) -> TelegramConflict.
- Outgoing messages are throttled to <= 1 per `min_send_interval` seconds.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

API_BASE = "https://api.telegram.org"
TOKEN_IN_TEXT = re.compile(r"bot\d{3,}:[A-Za-z0-9_-]+")
REDACTED = "bot<REDACTED>"
ALLOWED_UPDATES = ["message", "callback_query"]
MAX_MESSAGE_CHARS = 4096


def redact(text: object) -> str:
    return TOKEN_IN_TEXT.sub(REDACTED, str(text))


class _RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


_FILTER = _RedactTokenFilter()


def install_log_redaction() -> None:
    """httpx logs every request URL at INFO; the URL path contains the bot token."""
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
        if logger.level == logging.NOTSET or logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)


class TelegramError(Exception):
    def __init__(self, code: str, *, retry_after: float = 0.0, status: int | None = None) -> None:
        super().__init__(redact(code))
        self.code = redact(code)
        self.retry_after = retry_after
        self.status = status


class TelegramConflict(TelegramError):
    """409: another getUpdates poller (e.g. legacy com.automated-apply.rust) or a webhook."""


class TelegramRateLimited(TelegramError):
    pass


class TelegramUnauthorized(TelegramError):
    pass


class TelegramBadRequest(TelegramError):
    pass


class TelegramNetworkError(TelegramError):
    pass


class TelegramClient:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_sec: float = 15.0, min_send_interval: float = 1.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        if not token:
            raise ValueError("telegram token required")
        install_log_redaction()
        self._token = token
        self._http = httpx.AsyncClient(base_url=API_BASE, transport=transport,
                                       timeout=httpx.Timeout(timeout_sec, connect=10.0))
        self.min_send_interval = min_send_interval
        self._clock = clock
        self._sleep = sleeper
        self._send_lock = asyncio.Lock()
        self._last_send: float | None = None

    def __repr__(self) -> str:
        return "TelegramClient(token=<REDACTED>)"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, payload: dict[str, Any] | None = None, *,
                   timeout_sec: float | None = None) -> Any:
        try:
            response = await self._http.post(f"/bot{self._token}/{method}", json=payload or {},
                                             timeout=timeout_sec if timeout_sec is not None else httpx.USE_CLIENT_DEFAULT)
        except httpx.HTTPError as exc:
            raise TelegramNetworkError(f"network_error:{type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        status = response.status_code
        description = redact(str(body.get("description") or ""))[:200]
        if status == 409:
            raise TelegramConflict(f"conflict:{description or 'another getUpdates poller'}", status=409)
        if status == 429:
            retry = (body.get("parameters") or {}).get("retry_after", 5)
            raise TelegramRateLimited("rate_limited", retry_after=float(min(300, max(1, int(retry)))), status=429)
        if status in (401, 403, 404):
            raise TelegramUnauthorized(f"unauthorized:{status}", status=status)
        if status == 400:
            raise TelegramBadRequest(f"bad_request:{description}", status=400)
        if status >= 400 or not body.get("ok"):
            raise TelegramError(f"api_error:{status}", status=status)
        return body.get("result")

    async def _throttled(self, method: str, payload: dict[str, Any]) -> Any:
        async with self._send_lock:
            if self._last_send is not None:
                wait = self.min_send_interval - (self._clock() - self._last_send)
                if wait > 0:
                    await self._sleep(wait)
            try:
                return await self.call(method, payload)
            finally:
                self._last_send = self._clock()

    # --- Bot API methods ----------------------------------------------------------------
    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe")

    async def get_webhook_info(self) -> dict[str, Any]:
        return await self.call("getWebhookInfo")

    async def get_updates(self, offset: int | None, *, timeout: int = 25,
                          limit: int = 50) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "limit": limit, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload, timeout_sec=timeout + 15.0)
        return [u for u in result or [] if isinstance(u, dict) and isinstance(u.get("update_id"), int)]

    async def send_message(self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None,
                           reply_to: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:MAX_MESSAGE_CHARS], "parse_mode": "HTML",
                                   "disable_web_page_preview": True}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return await self._throttled("sendMessage", payload)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, *,
                                reply_markup: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text[:MAX_MESSAGE_CHARS],
                                   "parse_mode": "HTML", "disable_web_page_preview": True,
                                   "reply_markup": reply_markup or {"inline_keyboard": []}}
        return await self._throttled("editMessageText", payload)

    async def answer_callback_query(self, callback_id: str, text: str | None = None) -> Any:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:190]
        return await self.call("answerCallbackQuery", payload)
