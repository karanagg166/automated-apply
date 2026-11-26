"""Tier 3 of the read-only chain: the macOS Mail.app JXA reader (`mail_app_reader.js`, read-only)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.mail_v2.config import OSASCRIPT, MailConfig
from backend.app.mail_v2.read_models import (
    MAX_BODY_CHARS,
    MAX_MESSAGES,
    MailMessage,
    MailReadError,
)
from backend.app.mail_v2.read_parsing import _clean_text, message_key

READ_SCRIPT = Path(__file__).with_name("mail_app_reader.js")

ReadRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def osascript_read_runner(request: dict[str, Any]) -> dict[str, Any]:
    descriptor, path = tempfile.mkstemp(prefix="aa-mailread-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(request, handle)
        os.chmod(path, 0o600)
        child = await asyncio.create_subprocess_exec(
            str(OSASCRIPT), "-l", "JavaScript", str(READ_SCRIPT), path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, _ = await asyncio.wait_for(child.communicate(), 45)
        except TimeoutError:
            child.kill()
            await child.communicate()
            raise MailReadError("mail_app_timeout") from None
        if child.returncode or len(output) > 2_000_000:
            raise MailReadError("mail_app_scripting_unavailable")
        result = json.loads(output)
        if not isinstance(result, dict):
            raise MailReadError("mail_app_invalid_response")
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class MailAppReadClient:
    def __init__(self, config: MailConfig, *, runner: ReadRunner = osascript_read_runner,
                 available: bool | None = None) -> None:
        self.config = config
        self.runner = runner
        self.available = available  # None = detect (macOS + Mail.app present)

    @property
    def configured(self) -> bool:
        detected = self.config.mail_app_available if self.available is None else self.available
        return detected and not self.config.disabled

    async def recent(self, since: datetime, *, sender_domain: str | None = None,
                     limit: int = MAX_MESSAGES) -> list[MailMessage]:
        result = await self.runner({"action": "read_recent", "since_ms": int(since.timestamp() * 1000),
                                    "limit": limit, "max_chars": MAX_BODY_CHARS})
        if result.get("error") or not isinstance(result.get("messages"), list):
            raise MailReadError("mail_app_read_failed")
        messages = []
        for item in result["messages"]:
            if not isinstance(item, dict):
                continue
            received = datetime.fromtimestamp(item["received_ms"] / 1000, tz=UTC) \
                if isinstance(item.get("received_ms"), (int, float)) else None
            sender, subject = str(item.get("sender") or "")[:300], str(item.get("subject") or "")[:300]
            msg = MailMessage(message_key(item.get("message_id"), sender, subject, received), sender, subject,
                              received, _clean_text(str(item.get("body") or "")), "mail_app")
            if sender_domain and not msg.sender_domain.endswith(sender_domain.lower()):
                continue
            messages.append(msg)
        return messages
