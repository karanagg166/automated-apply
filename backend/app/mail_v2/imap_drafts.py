"""Primary draft channel: IMAP APPEND into Gmail's Drafts mailbox with the \\Draft flag.

Blocking imaplib calls run in `asyncio.to_thread`. Uses a Gmail App Password from the
private env (GMAIL_IMAP_EMAIL + GMAIL_IMAP_APP_PASSWORD). Works behind a locked screen
and never triggers a macOS Automation prompt. Read-only helpers (connection check,
recent drafts headers) open the mailbox with EXAMINE (readonly).
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesHeaderParser
from typing import Any

from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.message import APP_ID_HEADER

logger = logging.getLogger(__name__)
DEFAULT_DRAFTS = "[Gmail]/Drafts"
TIMEOUT_SEC = 20
_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>"(?:[^"\\]|\\.)*"|\S+)\s*$')


class ImapDraftError(Exception):
    """`ambiguous=True` means APPEND may have reached the server (never retry or fall back)."""

    def __init__(self, code: str, *, ambiguous: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class ImapReceipt:
    mailbox: str
    message_id: str | None


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_drafts_mailbox(lines: list[Any]) -> str | None:
    """The mailbox flagged \\Drafts (RFC 6154 special-use), else a localized [Gmail]/Drafts name."""
    fallback = None
    for raw in lines or []:
        if not isinstance(raw, bytes):
            continue
        match = _LIST_LINE.match(raw.strip())
        if not match:
            continue
        name = match.group("name")
        if name.startswith(b'"'):
            name = name[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
        decoded = name.decode("utf-8", errors="replace")
        if b"\\drafts" in match.group("flags").lower():
            return decoded
        if decoded.lower() in ("[gmail]/drafts", "[google mail]/drafts", "drafts"):
            fallback = fallback or decoded
    return fallback


ImapFactory = Callable[[str, int], Any]


def default_factory(host: str, port: int) -> Any:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SEC)


class ImapDraftClient:
    def __init__(self, config: MailConfig, *, factory: ImapFactory = default_factory) -> None:
        self.config = config
        self.factory = factory

    @property
    def configured(self) -> bool:
        return self.config.imap_configured

    def _connect(self) -> Any:
        if not self.configured:
            raise ImapDraftError("imap_unconfigured")
        try:
            imap = self.factory(self.config.imap_host, self.config.imap_port)
        except (OSError, ssl.SSLError, imaplib.IMAP4.error) as exc:
            raise ImapDraftError("imap_connection_failed:" + type(exc).__name__) from None
        try:
            imap.login(self.config.imap_email, self.config.imap_password)
        except imaplib.IMAP4.error:
            self._logout(imap)
            raise ImapDraftError("imap_auth_failed") from None
        except (OSError, ssl.SSLError) as exc:
            self._logout(imap)
            raise ImapDraftError("imap_connection_failed:" + type(exc).__name__) from None
        return imap

    @staticmethod
    def _logout(imap: Any) -> None:
        try:
            imap.logout()
        except Exception as exc:  # noqa: BLE001 - best-effort close
            logger.debug("imap logout ignored: %s", type(exc).__name__)

    def _drafts_mailbox(self, imap: Any) -> str:
        try:
            typ, lines = imap.list()
        except (imaplib.IMAP4.error, OSError):
            return DEFAULT_DRAFTS
        return (parse_drafts_mailbox(lines) if typ == "OK" else None) or DEFAULT_DRAFTS

    def _append(self, message: EmailMessage) -> ImapReceipt:
        imap = self._connect()
        try:
            mailbox = self._drafts_mailbox(imap)
            payload = message.as_bytes()
            try:
                typ, _ = imap.append(_quote(mailbox), r"(\Draft)", imaplib.Time2Internaldate(time.time()), payload)
            except imaplib.IMAP4.abort:
                raise ImapDraftError("imap_append_interrupted", ambiguous=True) from None
            except imaplib.IMAP4.error:
                raise ImapDraftError("imap_append_rejected") from None  # tagged NO/BAD: nothing stored
            except (OSError, ssl.SSLError):
                raise ImapDraftError("imap_append_interrupted", ambiguous=True) from None
            if typ != "OK":
                raise ImapDraftError("imap_append_rejected")
            return ImapReceipt(mailbox=mailbox, message_id=message.get("Message-ID"))
        finally:
            self._logout(imap)

    async def append_draft(self, message: EmailMessage) -> ImapReceipt:
        return await asyncio.to_thread(self._append, message)

    # --- read-only helpers ------------------------------------------------------------
    def _check(self) -> dict[str, Any]:
        imap = self._connect()
        try:
            mailbox = self._drafts_mailbox(imap)
            typ, data = imap.select(_quote(mailbox), readonly=True)
            count = int(data[0]) if typ == "OK" and data and data[0] and data[0].isdigit() else None
            return {"ok": typ == "OK", "drafts_mailbox": mailbox, "drafts_count": count}
        finally:
            self._logout(imap)

    async def check_connection(self) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._check)
        except ImapDraftError as exc:
            return {"ok": False, "error": exc.code}

    def _recent(self, limit: int) -> list[dict[str, Any]]:
        imap = self._connect()
        try:
            mailbox = self._drafts_mailbox(imap)
            typ, data = imap.select(_quote(mailbox), readonly=True)
            if typ != "OK" or not data or not data[0] or not data[0].isdigit():
                return []
            total = int(data[0])
            if total == 0:
                return []
            start = max(1, total - limit + 1)
            fields = f"(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE MESSAGE-ID {APP_ID_HEADER.upper()})])"
            typ, rows = imap.fetch(f"{start}:{total}", fields)
            output = []
            parser = BytesHeaderParser()
            for row in rows or []:
                if isinstance(row, tuple) and len(row) >= 2 and isinstance(row[1], bytes):
                    headers = parser.parsebytes(row[1])
                    output.append({"subject": headers.get("Subject"), "to": headers.get("To"),
                                   "date": headers.get("Date"), "message_id": headers.get("Message-ID"),
                                   "application_id": headers.get(APP_ID_HEADER)})
            return list(reversed(output))
        finally:
            self._logout(imap)

    async def list_recent_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._recent, max(1, min(limit, 50)))
