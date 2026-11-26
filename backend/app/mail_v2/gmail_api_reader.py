"""Tier 2 of the read-only chain: `gmail.readonly` via the existing GET-only GmailReadClient."""

from __future__ import annotations

import base64
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from backend.app.mail_v2.read_models import (
    MAX_BODY_CHARS,
    MAX_MESSAGES,
    MailMessage,
    MailReadError,
)
from backend.app.mail_v2.read_parsing import _clean_text, message_key

TokenProvider = Callable[[], Awaitable[str | None]]


def _gmail_text(payload: Mapping[str, Any], limit: int = MAX_BODY_CHARS) -> str:
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: Any, depth: int = 0) -> None:
        if depth > 10 or not isinstance(part, Mapping) or part.get("filename"):
            return
        data = (part.get("body") or {}).get("data")
        if isinstance(data, str) and len(data) < 400_000 and part.get("mimeType") in ("text/plain", "text/html"):
            try:
                text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                text = ""
            (plain if part.get("mimeType") == "text/plain" else rich).append(text)
        for child in part.get("parts") or []:
            walk(child, depth + 1)

    walk(payload)
    return _clean_text(" ".join(plain) if plain else " ".join(rich), limit)


class GmailApiReadClient:
    """Tier 2: `gmail.readonly` through the existing GET-only GmailReadClient."""

    def __init__(self, token_provider: TokenProvider | None = None, *, client: Any = None) -> None:
        self.token_provider = token_provider
        self.client = client

    @property
    def configured(self) -> bool:
        return self.token_provider is not None

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        from backend.app.integrations.gmail.read_client import GmailReadClient

        if self.token_provider is None:
            raise MailReadError("gmail_api_unconfigured")
        token = await self.token_provider()
        if not token:
            raise MailReadError("gmail_api_token_unavailable")
        reader = GmailReadClient(token, self.client)
        query = f"after:{int(since.timestamp())}" + (f" from:{sender_domain}" if sender_domain else "")
        try:
            listing = await reader.messages(labels=["INBOX"], query=query, limit=min(limit, 25))
            messages = []
            for item in (listing.get("messages") or [])[:limit]:
                full = await reader.message(item.get("id"), body=True)
                headers = {h.get("name", "").lower(): h.get("value", "")
                           for h in (full.get("payload") or {}).get("headers", []) if isinstance(h, dict)}
                received = None
                if str(full.get("internalDate", "")).isdigit():
                    received = datetime.fromtimestamp(int(full["internalDate"]) / 1000, tz=UTC)
                sender, subject = headers.get("from", "")[:300], headers.get("subject", "")[:300]
                messages.append(MailMessage(message_key(headers.get("message-id"), sender, subject, received),
                                            sender, subject, received, _gmail_text(full.get("payload") or {}),
                                            "gmail_api"))
            return messages
        except Exception as exc:  # noqa: BLE001 - provider errors are fixed internal codes only
            code = exc.args[0] if exc.args and isinstance(exc.args[0], str) else type(exc).__name__
            raise MailReadError("gmail_api:" + re.sub(r"[^a-z0-9_]", "", code.lower())[:40]) from None
