"""Durable, backend-only single-use consent and immutable send identities."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin


class SendConfirmation(Base):
    __tablename__ = "outreach_send_confirmations"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("outreach_logs.id"))
    connected_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("connected_accounts.id")
    )
    actor_id: Mapped[str] = mapped_column(String(64))
    draft_revision: Mapped[int] = mapped_column(Integer)
    approval_hash: Mapped[str] = mapped_column(String(64))
    recipient_email: Mapped[str] = mapped_column(String(254))
    sender_email: Mapped[str] = mapped_column(String(254))
    sender_binding: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutreachSendAttempt(Base, TimestampMixin):
    __tablename__ = "outreach_send_attempts"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("outreach_logs.id"), unique=True
    )
    connected_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("connected_accounts.id")
    )
    confirmation_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("outreach_send_confirmations.token_hash"), unique=True
    )
    actor_id: Mapped[str] = mapped_column(String(64))
    draft_revision: Mapped[int] = mapped_column(Integer)
    approval_hash: Mapped[str] = mapped_column(String(64))
    recipient_email: Mapped[str] = mapped_column(String(254))
    sender_email: Mapped[str] = mapped_column(String(254))
    sender_binding: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    content_digest: Mapped[str] = mapped_column(String(64))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    rfc_message_id: Mapped[str] = mapped_column(String(255), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="prepared")
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(64))
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciled_by: Mapped[str | None] = mapped_column(String(64))
    reconciliation_note: Mapped[str | None] = mapped_column(Text)
