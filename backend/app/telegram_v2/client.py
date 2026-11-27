"""Minimal async Telegram Bot API client (httpx) with token redaction.

- The token only ever appears in the request path; exceptions carry a short
  code (never the URL), and httpx/httpcore log records are redacted.
- HTTP 409 (another getUpdates poller or a webhook) -> TelegramConflict.
- Outgoing messages are throttled to <= 1 per `min_send_interval` seconds.
- Phase 8: long texts are split into <= 4000 UTF-16-unit chunks (Telegram counts UTF-16),
  and a `can't parse entities` 400 is retried once as plain text (tags stripped,
  entities unescaped), so a job title with `<`, `&` or a stray tag never loses a message.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
TOKEN_IN_TEXT = re.compile(r"bot\d{3,}:[A-Za-z0-9_-]+")
REDACTED = "bot<REDACTED>"
ALLOWED_UPDATES = ["message", "callback_query"]
MAX_MESSAGE_CHARS = 4096
CHUNK_UNITS = 4000  # safety margin under Telegram's 4096 UTF-16 code units
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
MAX_RATE_LIMIT_RETRIES = 3  # 429: wait retry_after + 0.5 s, then resend (never drop the message)
AUTH_CIRCUIT_SEC = 15 * 60  # 401/403/404: stop sending for 15 min instead of hammering the API
GLOBAL_MIN_INTERVAL = 1 / 25  # Telegram: <= ~30 msg/s across chats; stay at 25
PARSE_ERROR = re.compile(r"can't parse entities|can't find end|unsupported start tag|unexpected end tag|"
                         r"entity|parse", re.IGNORECASE)


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def html_to_plain(text: str) -> str:
    """Telegram-HTML -> plain text (fallback when Telegram rejects the markup)."""
    return html.unescape(_TAG.sub("", text or ""))


def _cut(text: str, units: int) -> int:
    """Largest prefix length (in str indices) whose UTF-16 length is <= units."""
    if utf16_len(text) <= units:
        return len(text)
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if utf16_len(text[:mid]) <= units:
            low = mid
        else:
            high = mid - 1
    return max(1, low)


def split_message(text: str, limit: int = CHUNK_UNITS) -> list[str]:
    """Split on line boundaries (then spaces, then hard cuts) into chunks <= `limit` UTF-16 units.

    Our HTML is line-local (one tag pair per line), so line splits keep tags balanced; a
    chunk that still fails to parse is resent as plain text by `send_message`.
    """
    text = text or ""
    if utf16_len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = line if not current else current + "\n" + line
        if utf16_len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while utf16_len(line) > limit:
            cut = _cut(line, limit)
            space = line.rfind(" ", 0, cut)
            if space > cut // 2:
                cut = space
            # never split inside an HTML entity or tag
            amp, semi = line.rfind("&", 0, cut), line.rfind(";", 0, cut)
            if amp > semi and cut - amp <= 10:
                cut = amp
            lt, gt = line.rfind("<", 0, cut), line.rfind(">", 0, cut)
            if lt > gt and lt > 0:
                cut = lt
            chunks.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        current = line
    if current or not chunks:
        chunks.append(current)
    return [c for c in chunks if c.strip()] or [text[: _cut(text, limit)]]


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


def is_parse_error(exc: TelegramError) -> bool:
    return isinstance(exc, TelegramBadRequest) and bool(PARSE_ERROR.search(exc.code))


def is_not_modified(exc: TelegramError) -> bool:
    return isinstance(exc, TelegramBadRequest) and "not modified" in exc.code.lower()


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
        self._chat_last: dict[Any, float] = {}
        self._paused_until = 0.0  # 429 flood-wait: every outbound send waits
        self._circuit_until = 0.0  # 401/403/404 circuit
        self._circuit_code: str | None = None
        self.rate_limited = 0  # counters for /health
        self.dropped_by_circuit = 0

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

    @property
    def circuit_open(self) -> bool:
        return self._clock() < self._circuit_until

    def _spacing_wait(self, chat: Any) -> float:
        now = self._clock()
        waits = [self._paused_until - now]
        if self._last_send is not None:
            waits.append(min(GLOBAL_MIN_INTERVAL, self.min_send_interval) - (now - self._last_send))
        last_chat = self._chat_last.get(chat)
        if last_chat is not None:
            waits.append(self.min_send_interval - (now - last_chat))
        return max(0.0, *waits)

    async def _throttled(self, method: str, payload: dict[str, Any]) -> Any:
        """Serialized sends: <= 1 msg/s per chat, <= 25/s overall, 429 retry_after honoured for the
        whole outbound path (re-sent, never dropped), 401/403/404 trip a 15-min circuit."""
        chat = payload.get("chat_id")
        async with self._send_lock:
            for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                if self.circuit_open:
                    self.dropped_by_circuit += 1
                    raise TelegramUnauthorized(self._circuit_code or "unauthorized:circuit_open")
                wait = self._spacing_wait(chat)
                if wait > 0:
                    await self._sleep(wait)
                try:
                    return await self.call(method, payload)
                except TelegramRateLimited as exc:
                    self.rate_limited += 1
                    self._paused_until = self._clock() + exc.retry_after + 0.5
                    if attempt >= MAX_RATE_LIMIT_RETRIES:
                        raise
                    logger.warning("telegram 429 on %s: pausing outbound %.1fs", method, exc.retry_after + 0.5)
                except TelegramUnauthorized as exc:
                    self._circuit_until = self._clock() + AUTH_CIRCUIT_SEC
                    self._circuit_code = exc.code
                    logger.error("telegram %s on %s: outbound circuit OPEN for %ss (check the bot token / "
                                 "that the owner has not blocked the bot)", exc.code, method, AUTH_CIRCUIT_SEC)
                    raise
                finally:
                    self._last_send = self._clock()
                    if chat is not None:
                        self._chat_last[chat] = self._last_send
            raise AssertionError("unreachable")  # pragma: no cover

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
                           reply_to: int | None = None, parse_mode: str | None = "HTML",
                           silent: bool = False) -> dict[str, Any]:
        """Send `text` (chunked); the keyboard rides on the last chunk, the reply on the first.

        Returns the last chunk's Message (the one carrying the buttons).
        """
        chunks = split_message(text)
        result: dict[str, Any] = {}
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            result = await self._send_one(chat_id, chunk, reply_markup=reply_markup if last else None,
                                          reply_to=reply_to if index == 0 else None, parse_mode=parse_mode,
                                          silent=silent)
        return result

    async def _send_one(self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None,
                        reply_to: int | None, parse_mode: str | None, silent: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if silent:
            payload["disable_notification"] = True
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            return await self._throttled("sendMessage", payload)
        except TelegramBadRequest as exc:
            if not parse_mode or not is_parse_error(exc):
                raise
            # Unescaped title/company or a split tag: resend the same content as plain text.
            plain = {k: v for k, v in payload.items() if k != "parse_mode"}
            plain["text"] = html_to_plain(text)[: _cut(html_to_plain(text), MAX_MESSAGE_CHARS - 96)] or "…"
            return await self._throttled("sendMessage", plain)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, *,
                                reply_markup: dict[str, Any] | None = None) -> Any:
        body = text if utf16_len(text) <= CHUNK_UNITS else html_to_plain(text)
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id,
                                   "text": body[: _cut(body, CHUNK_UNITS)],
                                   "disable_web_page_preview": True,
                                   "reply_markup": reply_markup or {"inline_keyboard": []}}
        if body is text:
            payload["parse_mode"] = "HTML"
        try:
            return await self._throttled("editMessageText", payload)
        except TelegramBadRequest as exc:
            if "parse_mode" not in payload or not is_parse_error(exc):
                raise
            payload.pop("parse_mode")
            payload["text"] = html_to_plain(text)[: _cut(html_to_plain(text), CHUNK_UNITS)] or "…"
            return await self._throttled("editMessageText", payload)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> Any:
        """'typing…' indicator (Telegram shows it ~5 s). Not throttled: it is not a message."""
        return await self.call("sendChatAction", {"chat_id": chat_id, "action": action})

    async def delete_webhook(self) -> Any:
        """Long-polling mode: a stale webhook makes every getUpdates 409 (pending updates are kept)."""
        return await self.call("deleteWebhook", {"drop_pending_updates": False})

    async def set_my_commands(self, commands: list[tuple[str, str]]) -> Any:
        return await self.call("setMyCommands", {"commands": [
            {"command": name, "description": description[:256]} for name, description in commands]})

    async def answer_callback_query(self, callback_id: str, text: str | None = None) -> Any:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:190]
        return await self.call("answerCallbackQuery", payload)
