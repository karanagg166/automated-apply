"""Outreach log model with Human-in-the-Loop state machine."""

import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, TimestampMixin


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

    # Relationships
    job = relationship("Job", back_populates="outreach_logs")
    contact = relationship("Contact", back_populates="outreach_logs")
