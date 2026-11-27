"""Followup 007 value objects: Telegram notification ledger rows and digest queue items."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

DEDUP_KEY = re.compile(r"^[a-z0-9_.:-]{3,64}$")
MAX_DIGEST_TEXT = 600


@dataclass
class LedgerEntry:
    dedup_key: str
    topic: str
    priority: int
    last_event_at: datetime | None = None
    last_sent_at: datetime | None = None
    suppressed_count: int = 0
    chat_id: int | None = None
    message_id: int | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class DigestItem:
    id: str
    topic: str
    priority: int
    text: str
    dedup_key: str | None = None
    created_at: datetime | None = None


def check_dedup_key(key: str) -> str:
    if not DEDUP_KEY.match(key or ""):
        raise ValueError("invalid dedup_key")
    return key


def bound_digest_text(text: str) -> str:
    value = " ".join((text or "").split())
    return (value[: MAX_DIGEST_TEXT - 1] + "…") if len(value) > MAX_DIGEST_TEXT else (value or "…")
