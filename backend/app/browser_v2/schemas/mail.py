"""Phase 5 Gmail drafts, enrichment and mail-bridge contracts (+ Phase 6A recruiter replies)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Phase 5: quota-hit Gmail drafts, enrichment and the mail bridge ----------------------
DraftChannelName = Literal["imap", "mail_app"]
DraftStatusName = Literal["PENDING", "CREATED", "FAILED"]
GMAIL_PERMISSION_LABEL = "Gmail Permission: Read + Draft Only (Sending Disabled)"


class EmailDraftRead(BaseModel):
    id: str
    application_id: str | None
    platform: str | None
    company_name: str | None
    role_title: str | None
    recipient_email: str | None
    subject: str | None
    body_preview: str | None
    channel: DraftChannelName | None
    status: DraftStatusName
    composer: Literal["llm", "template"] | None
    enrichment_source: str | None
    last_error: str | None
    created_at: datetime | None
    application_state: str | None = Field(description="Current application state (retry status)")
    retry_after: datetime | None = Field(description="Next portal retry (DRAFTED_AND_QUEUED)")


class EmailDraftPage(BaseModel):
    items: list[EmailDraftRead]
    total: int
    limit: int
    offset: int


class EnrichmentProviderRead(BaseModel):
    provider: Literal["apollo", "apify", "signalhire"]
    configured: bool
    state: Literal["unconfigured", "available", "cooldown", "cap_reached"]
    daily_cap: int
    used_today: int
    period_key: str = Field(description="YYYY-MM-DD in Asia/Kolkata")
    cooldown_until: datetime | None
    last_error: str | None
    key_env: str = Field(description="Env var that configures the provider (value never returned)")


class EnrichmentStatusRead(BaseModel):
    backend: Literal["postgres", "memory"]
    disabled: bool
    fetch_pages: bool
    providers: list[EnrichmentProviderRead]
    cached_domains: int


class MailStatusRead(BaseModel):
    permission: Literal["READ_AND_DRAFT_ONLY"] = "READ_AND_DRAFT_ONLY"
    permission_label: str = GMAIL_PERMISSION_LABEL
    disabled: bool
    channel_mode: Literal["auto", "imap", "mail_app"]
    active_channel: Literal["imap", "mail_app", "unconfigured"]
    imap_configured: bool
    imap_email: str | None = Field(description="Masked address, e.g. ka•••@gmail.com")
    imap_host: str
    mail_app_available: bool
    mail_app_disabled: bool
    resume_attachment_configured: bool


class DraftNowRead(BaseModel):
    ok: bool
    code: Literal["drafted", "already_drafted", "no_email_found", "draft_failed", "mail_unconfigured"]
    message: str
    channel: DraftChannelName | None = None
    enrichment_status: str | None = None
    enrichment_source: str | None = None
    draft: EmailDraftRead | None = None


class MailEventRead(BaseModel):
    id: str | None = None
    kind: Literal["RECRUITER_REPLY", "INTERVIEW", "JOB_ALERT"]
    source: str
    platform: str | None = None
    company_name: str | None = None
    sender: str | None = None
    subject: str | None = None
    snippet: str | None = None
    application_id: str | None = None
    received_at: datetime | None = None
    alerted_at: datetime | None = None
    created_at: datetime | None = None


class MailReplyPage(BaseModel):
    permission: Literal["READ_ONLY"] = "READ_ONLY"
    configured: bool
    tiers: dict[str, bool]
    items: list[MailEventRead]
