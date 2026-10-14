"""Job database model."""

import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Text, Boolean, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, TimestampMixin


class Job(Base, TimestampMixin):
    """Represents a job vacancy discovered across platforms."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    experience_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skills_required: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True, index=True)
    match_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="discovered", nullable=False, index=True)
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="jobs")
    outreach_logs = relationship("OutreachLog", back_populates="job")
