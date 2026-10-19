"""Outreach log model with Human-in-the-Loop state machine."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import GUID, Base, TimestampMixin


class OutreachLog(Base, TimestampMixin):
    """Tracks email draft generation, approval states, and delivery status."""

    __tablename__ = "outreach_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resume_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gmail_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(50),
        default="draft_created",
        nullable=False,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_account_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("connected_accounts.id", ondelete="SET NULL"))
    draft_revision: Mapped[int] = mapped_column(Integer, default=1)
    candidate_profile_version: Mapped[int | None] = mapped_column(Integer)
    recipient_email: Mapped[str | None] = mapped_column(String(254))
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    approval_hash: Mapped[str | None] = mapped_column(String(64))
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_status: Mapped[str] = mapped_column(String(30), default="needs_review")
    generation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_via: Mapped[str] = mapped_column(String(20), default="legacy")
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    __mapper_args__ = {"version_id_col": draft_revision}

    # Relationships
    job = relationship("Job", back_populates="outreach_logs")
    contact = relationship("Contact", back_populates="outreach_logs")
