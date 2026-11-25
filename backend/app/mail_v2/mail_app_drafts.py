"""Fallback draft channel: a silent macOS Mail.app outgoing message (JXA via osascript).

- The request (recipient, subject, body, attachment path) is written to a 0600 temp JSON
  file and only its path is passed in argv: no shell, no string interpolation into
  script source, so job titles/company names can never inject AppleScript or shell.
- The script never brings Mail to the foreground (stalls behind a locked screen) and has
  no delivery operation at all; tests assert both by scanning mail_app_drafts.js.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.mail_v2.config import OSASCRIPT, MailConfig

SCRIPT = Path(__file__).with_name("mail_app_drafts.js")
TIMEOUT_SEC = 45
AUTOMATION_DENIED = -1743


class MailAppDraftError(Exception):
    def __init__(self, code: str, *, ambiguous: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class MailAppReceipt:
    draft_id: str | None
    attached: bool


Runner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def osascript_runner(request: dict[str, Any]) -> dict[str, Any]:
    """Run the JXA helper with the request in a private temp file (argv carries only its path)."""
    descriptor, path = tempfile.mkstemp(prefix="aa-mail-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(request, handle)
        os.chmod(path, 0o600)
        child = await asyncio.create_subprocess_exec(
            str(OSASCRIPT), "-l", "JavaScript", str(SCRIPT), path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, _ = await asyncio.wait_for(child.communicate(), TIMEOUT_SEC)
        except TimeoutError:
            child.kill()
            await child.communicate()
            raise MailAppDraftError("mail_app_timeout", ambiguous=request.get("action") == "draft") from None
        if child.returncode or len(output) > 65536:
            raise MailAppDraftError("mail_app_scripting_unavailable")
        try:
            result = json.loads(output)
        except ValueError:
            raise MailAppDraftError("mail_app_invalid_response", ambiguous=request.get("action") == "draft") \
                from None
        if not isinstance(result, dict):
            raise MailAppDraftError("mail_app_invalid_response")
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class MailAppDraftClient:
    def __init__(self, config: MailConfig, *, runner: Runner = osascript_runner) -> None:
        self.config = config
        self.runner = runner

    @property
    def available(self) -> bool:
        return self.config.mail_app_available

    async def save_draft(self, *, recipient: str, subject: str, body: str,
                         attachment: Path | None = None) -> MailAppReceipt:
        if not self.available:
            raise MailAppDraftError("mail_app_unavailable")
        request: dict[str, Any] = {"action": "draft", "recipient": recipient, "subject": subject, "body": body}
        if self.config.mail_app_sender:
            request["sender"] = self.config.mail_app_sender
        if attachment is not None:
            request["attachment"] = str(attachment)
        result = await self.runner(request)
        if result.get("error"):
            if result.get("apple_event_code") == AUTOMATION_DENIED:
                raise MailAppDraftError("mail_app_automation_permission_required")
            raise MailAppDraftError("mail_app_draft_failed")
        if result.get("saved") is not True:
            raise MailAppDraftError("mail_app_draft_unconfirmed", ambiguous=True)
        return MailAppReceipt(draft_id=str(result.get("draft_id") or "") or None,
                              attached=bool(result.get("attached")))

    async def probe(self) -> dict[str, Any]:
        """Opt-in check (may show the one-time macOS Automation consent prompt)."""
        if not self.available:
            return {"ok": False, "error": "mail_app_unavailable"}
        try:
            result = await self.runner({"action": "probe"})
        except MailAppDraftError as exc:
            return {"ok": False, "error": exc.code}
        if result.get("error"):
            code = result.get("apple_event_code")
            return {"ok": False, "error": "mail_app_automation_permission_required"
                    if code == AUTOMATION_DENIED else "mail_app_not_ready"}
        return {"ok": True, "accounts": result.get("accounts")}
