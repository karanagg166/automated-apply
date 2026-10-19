"""Contact database model."""

import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, JSON, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, TimestampMixin


class Contact(Base, TimestampMixin):
    """Represents a discovered professional contact (recruiter, hiring manager, etc.)."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("company_id", "email", name="uq_contacts_company_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    linkedin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    email_status: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00, nullable=False)
    enrichment_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_review_notes: Mapped[str | None] = mapped_column(Text)
    human_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    company = relationship("Company", back_populates="contacts")
    outreach_logs = relationship("OutreachLog", back_populates="contact")
