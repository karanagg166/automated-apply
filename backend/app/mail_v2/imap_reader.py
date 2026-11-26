"""Tier 1 of the read-only chain: EXAMINE-only Gmail IMAP (BODY.PEEK[]; never sets \\Seen)."""

from __future__ import annotations

import asyncio
import imaplib
import re
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.read_models import (
    MAX_MESSAGES,
    TIMEOUT_SEC,
    MailMessage,
    MailReadError,
)
from backend.app.mail_v2.read_parsing import parse_rfc822

# --- tier clients -------------------------------------------------------------------------------
ImapFactory = Callable[[str, int], Any]


def default_imap_factory(host: str, port: int) -> Any:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SEC)


class ImapReadClient:
    """EXAMINE-only Gmail IMAP reader. Allowed calls: login, select(readonly), search, fetch, logout."""

    def __init__(self, config: MailConfig, *, factory: ImapFactory = default_imap_factory,
                 mailbox: str = "INBOX") -> None:
        self.config = config
        self.factory = factory
        self.mailbox = mailbox

    @property
    def configured(self) -> bool:
        return self.config.imap_configured and not self.config.disabled

    def _read(self, since: datetime, sender_domain: str | None, limit: int) -> list[MailMessage]:
        try:
            imap = self.factory(self.config.imap_host, self.config.imap_port)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailReadError("imap_" + type(exc).__name__.lower()) from None
        try:
            imap.login(self.config.imap_email, self.config.imap_password)
            status, _ = imap.select('"' + self.mailbox + '"', readonly=True)  # EXAMINE
            if status != "OK":
                raise MailReadError("imap_examine_failed")
            criteria = ["SINCE", since.astimezone(UTC).strftime("%d-%b-%Y")]
            if sender_domain:
                criteria += ["FROM", '"' + re.sub(r'[^A-Za-z0-9.@-]', "", sender_domain) + '"']
            status, data = imap.search(None, *criteria)
            if status != "OK":
                raise MailReadError("imap_search_failed")
            ids = (data[0] or b"").split()[-limit:]
            messages = []
            for number in reversed(ids):
                status, parts = imap.fetch(number, "(BODY.PEEK[])")  # PEEK: never sets \\Seen
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
                if status == "OK" and raw:
                    messages.append(parse_rfc822(raw, "imap"))
            return messages
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailReadError("imap_" + type(exc).__name__.lower()) from None
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001, S110
                pass

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        return await asyncio.to_thread(self._read, since, sender_domain, limit)
