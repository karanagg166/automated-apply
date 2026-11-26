"""Telegram v2 configuration from the project .env overlaid by the process env.

Reuses the legacy variable names (set them in the project `.env`):
TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID and (optional, stricter)
TELEGRAM_OWNER_USER_ID. Missing values mean `unconfigured`, never an error.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_OWNER_CHAT_ID"
USER_ENV = "TELEGRAM_OWNER_USER_ID"
DISABLE_ENV = "TELEGRAM_V2_DISABLED"
TOKEN_PATTERN = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,64}$")


def _int(value: str | None) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number != 0 else None


@dataclass(frozen=True)
class TelegramConfig:
    token: str | None = field(default=None, repr=False)
    owner_chat_id: int | None = None
    owner_user_id: int | None = None
    disabled: bool = False
    problem: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token and self.owner_chat_id and not self.problem and not self.disabled)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelegramConfig:
        if env is None:
            from backend.app.ai_v2.router import load_env

            env = load_env()
        token = (env.get(TOKEN_ENV) or "").strip() or None
        chat = _int(env.get(CHAT_ENV))
        user = _int(env.get(USER_ENV))
        disabled = (env.get(DISABLE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}
        missing = [name for name, value in ((TOKEN_ENV, token), (CHAT_ENV, chat)) if not value]
        problem = None
        if missing:
            problem = "missing " + " + ".join(missing)
        elif token is not None and not TOKEN_PATTERN.match(token):
            problem = f"{TOKEN_ENV} is malformed"
        elif disabled:
            problem = f"disabled by {DISABLE_ENV}"
        return cls(token=token, owner_chat_id=chat, owner_user_id=user, disabled=disabled, problem=problem)

    def masked_chat_id(self) -> str | None:
        if self.owner_chat_id is None:
            return None
        text = str(self.owner_chat_id)
        return "•" * max(0, len(text) - 3) + text[-3:]

    def public(self) -> dict[str, Any]:
        """Safe to print or return from the API: never the token."""
        return {"configured": self.configured, "problem": self.problem,
                "owner_chat_id": self.masked_chat_id(), "owner_user_id_enforced": self.owner_user_id is not None,
                "token_present": bool(self.token), "env_vars": [TOKEN_ENV, CHAT_ENV, USER_ENV]}
