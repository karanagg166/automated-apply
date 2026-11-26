"""Phase 4 Telegram HITL + dashboard inbox contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

# --- Phase 4: Telegram HITL + dashboard inbox -------------------------------------------
HitlKindName = Literal["CAPTCHA", "OTP", "AUTH", "QUESTION", "ERROR"]
HitlStatusName = Literal["OPEN", "ANSWERED", "EXPIRED", "CANCELLED"]
PollingStateName = Literal["unconfigured", "starting", "polling", "conflict", "error", "stopped"]


class HitlRead(BaseModel):
    id: str
    ref: str
    application_id: str | None
    platform: str
    kind: HitlKindName
    status: HitlStatusName
    question: str
    options: list[str]
    resolver_reason: str | None
    company: str | None
    title: str | None
    job_url: str | None
    application_state: str | None
    telegram_msg_id: int | None
    answer_text: str | None
    resolved_via: str | None
    created_at: datetime | None
    resolved_at: datetime | None
    consumed_at: datetime | None


class HitlPage(BaseModel):
    items: list[HitlRead]
    total: int
    limit: int
    offset: int


class HitlResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=1000)
    cache_answer: StrictBool = True


class HitlResolutionRead(BaseModel):
    ok: bool
    code: str
    message: str
    answer: str | None
    cached: bool
    requeued: bool
    application_state: str | None
    options: list[str]
    hitl: HitlRead | None


class TelegramStatusRead(BaseModel):
    configured: bool
    polling_state: PollingStateName
    stale: bool
    conflict_detected: bool
    conflict_detected_at: datetime | None
    last_poll_at: datetime | None
    last_update_id: int | None
    last_error: str | None
    owner_chat_id: str | None
    open_hitl_count: int


class ResumeAuthRead(BaseModel):
    ok: bool
    platform: str
    message: str
    auth_status: str | None
    resolved_auth_requests: int
