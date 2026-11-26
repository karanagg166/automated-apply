"""Mail draft bridge configuration (project .env / process env; secrets never logged)."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHANNELS = ("auto", "imap", "mail_app")
TRUE = {"1", "true", "yes", "on"}
MAIL_APP_PATHS = (Path("/System/Applications/Mail.app"), Path("/Applications/Mail.app"))
OSASCRIPT = Path("/usr/bin/osascript")


@dataclass(frozen=True)
class MailConfig:
    imap_email: str | None = None
    imap_password: str | None = None
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    channel: str = "auto"
    mail_app_sender: str | None = None
    mail_app_disabled: bool = False
    resume_path: str | None = None
    disabled: bool = False

    def __repr__(self) -> str:  # never print the app password
        return (f"MailConfig(imap_configured={self.imap_configured}, channel={self.channel!r}, "
                f"mail_app_disabled={self.mail_app_disabled}, disabled={self.disabled})")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MailConfig:
        if env is None:
            from backend.app.ai_v2.router import load_env

            env = load_env()
        channel = (env.get("MAIL_DRAFT_CHANNEL") or "auto").strip().lower()
        try:
            port = int(env.get("GMAIL_IMAP_PORT") or 993)
        except ValueError:
            port = 993
        password = "".join((env.get("GMAIL_IMAP_APP_PASSWORD") or "").split())  # Gmail shows it in 4 groups
        return cls(
            imap_email=(env.get("GMAIL_IMAP_EMAIL") or "").strip() or None,
            imap_password=password or None,
            imap_host=(env.get("GMAIL_IMAP_HOST") or "imap.gmail.com").strip(),
            imap_port=port,
            channel=channel if channel in CHANNELS else "auto",
            mail_app_sender=(env.get("MAIL_APP_SENDER") or "").strip() or None,
            mail_app_disabled=(env.get("MAIL_APP_FALLBACK_DISABLED") or "").strip().lower() in TRUE,
            resume_path=(env.get("MAIL_DRAFT_RESUME_PATH") or "").strip() or None,
            disabled=(env.get("MAIL_V2_DISABLED") or "").strip().lower() in TRUE,
        )

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_email and self.imap_password)

    @property
    def mail_app_available(self) -> bool:
        """macOS with osascript and Mail.app installed (does not launch Mail or prompt TCC)."""
        return (not self.mail_app_disabled and sys.platform == "darwin" and OSASCRIPT.exists()
                and any(path.exists() for path in MAIL_APP_PATHS))

    def active_channel(self) -> str:
        """imap | mail_app | unconfigured — the channel a draft would use right now."""
        if self.disabled:
            return "unconfigured"
        if self.channel in ("auto", "imap") and self.imap_configured:
            return "imap"
        if self.channel in ("auto", "mail_app") and self.mail_app_available:
            return "mail_app"
        return "unconfigured"

    def masked_email(self) -> str | None:
        if not self.imap_email or "@" not in self.imap_email:
            return None
        local, domain = self.imap_email.split("@", 1)
        return f"{local[:2]}•••@{domain}"

    def public(self) -> dict[str, Any]:
        return {"permission": "READ_AND_DRAFT_ONLY", "disabled": self.disabled, "channel_mode": self.channel,
                "active_channel": self.active_channel(), "imap_configured": self.imap_configured,
                "imap_email": self.masked_email(), "imap_host": self.imap_host,
                "mail_app_available": self.mail_app_available, "mail_app_disabled": self.mail_app_disabled,
                "resume_attachment_configured": bool(self.resume_path and os.path.isfile(self.resume_path)),
                "env": {"imap_email": "GMAIL_IMAP_EMAIL", "imap_password": "GMAIL_IMAP_APP_PASSWORD",
                        "channel": "MAIL_DRAFT_CHANNEL", "resume": "MAIL_DRAFT_RESUME_PATH"}}
