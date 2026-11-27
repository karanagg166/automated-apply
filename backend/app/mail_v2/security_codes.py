"""Greenhouse post-submit email security codes (READ-ONLY mail access, Milestone 2).

After the first Submit, Greenhouse may email an 8-character security code and hold the
application until it is typed back. This finds that code strictly:

* only messages received after `since` (the submit click minus a small skew) - an older
  code is never reused;
* only from Greenhouse's own sender domains (greenhouse-mail.io / greenhouse.io);
* only when the (normalized) company name appears in the subject or body;
* the newest qualifying message wins.

The raw code is returned to the caller only; it is never logged or stored (see `mask_code`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.app.mail_v2.read_models import MailReadError

logger = logging.getLogger(__name__)

GREENHOUSE_SENDER = re.compile(r"(?:^|\.)greenhouse(?:-mail)?\.io$", re.IGNORECASE)
CODE_PHRASE = re.compile(r"security code|verification code|confirmation code|one[- ]time code|"
                         r"\bcode\b", re.IGNORECASE)
CODE_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{8})(?![A-Za-z0-9])")
COMPANY_SUFFIX = re.compile(r"\b(?:inc|llc|ltd|limited|pvt|private|corp|corporation|co|gmbh|plc|technologies|"
                            r"technology|labs|hq)\b\.?", re.IGNORECASE)
DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_INTERVAL_SEC = 5.0
CLOCK_SKEW = timedelta(seconds=10)


@dataclass(frozen=True)
class SecurityCodeHit:
    code: str
    message_key: str
    received_at: datetime


def mask_code(code: str | None) -> str:
    """Log-safe form of a code: its length only."""
    return f"<code len={len(code)}>" if code else "<none>"


def normalize_company(value: str | None) -> str:
    text = COMPANY_SUFFIX.sub(" ", (value or "").casefold())
    return re.sub(r"[^a-z0-9]", "", text)


def _code_like(token: str) -> bool:
    """An 8-char code has a digit or >= 2 capitals ("Security", "password" are plain words)."""
    return any(c.isdigit() for c in token) or sum(c.isupper() for c in token) >= 2


def extract_security_code(text: str) -> str | None:
    """The 8-character code right after a code phrase (else the first code-like token)."""
    text = text or ""
    for phrase in CODE_PHRASE.finditer(text):
        window = text[phrase.end(): phrase.end() + 160]
        for match in CODE_TOKEN.finditer(window):
            if _code_like(match.group(1)):
                return match.group(1)
    return None


def mentions_company(message: Any, company: str | None) -> bool:
    wanted = normalize_company(company)
    if len(wanted) < 2:
        return False
    haystack = re.sub(r"[^a-z0-9]", "", f"{message.subject} {message.body}".casefold())
    return wanted in haystack


async def find_security_code(reader: Any, company: str | None, since: datetime) -> SecurityCodeHit | None:
    """Newest qualifying Greenhouse code received at/after `since`; MailReadError propagates."""
    messages = await reader.recent(since - timedelta(days=1), limit=20)  # IMAP SINCE is day-granular
    hits: list[SecurityCodeHit] = []
    for message in messages:
        if message.received_at is None or message.received_at < since:
            continue  # unknown or older than this submit: never reuse
        if not GREENHOUSE_SENDER.search(message.sender_domain or ""):
            continue
        if not mentions_company(message, company):
            continue
        code = extract_security_code(f"{message.subject}\n{message.body}")
        if code:
            hits.append(SecurityCodeHit(code, message.key, message.received_at))
    if not hits:
        return None
    return max(hits, key=lambda hit: hit.received_at)


Sleeper = Callable[[float], Awaitable[Any]]


async def poll_security_code(reader: Any, company: str | None, submitted_at: datetime, *,
                             timeout_s: float = DEFAULT_TIMEOUT_SEC, interval_s: float = DEFAULT_INTERVAL_SEC,
                             sleep: Sleeper = asyncio.sleep) -> str | None:
    """Poll every `interval_s` up to `timeout_s`; None on timeout or when mail is unavailable."""
    since = submitted_at - CLOCK_SKEW
    waited = 0.0
    while True:
        try:
            hit = await find_security_code(reader, company, since)
        except MailReadError as exc:
            logger.info("greenhouse security code: mail unavailable (%s)", exc.code)
            return None
        except Exception as exc:  # noqa: BLE001 - a reader bug degrades to the owner HITL
            logger.info("greenhouse security code: reader error (%s)", type(exc).__name__)
            return None
        if hit is not None:
            logger.info("greenhouse security code found %s", mask_code(hit.code))
            return hit.code
        if waited >= timeout_s:
            return None
        await sleep(interval_s)
        waited += interval_s


def security_code_provider(reader: Any, env: dict[str, str] | None = None
                           ) -> Callable[[str | None, datetime], Awaitable[str | None]]:
    """The callable the hosted-ATS applier awaits (GREENHOUSE_OTP_TIMEOUT_SECONDS, default 120)."""
    try:
        timeout = float((env or {}).get("GREENHOUSE_OTP_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SEC)
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SEC
    timeout = min(max(timeout, 0.0), 300.0)

    async def provide(company: str | None, submitted_at: datetime) -> str | None:
        return await poll_security_code(reader, company, submitted_at, timeout_s=timeout)

    return provide
