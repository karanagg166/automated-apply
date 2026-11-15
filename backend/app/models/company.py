"""Company database model."""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import GUID, Base, TimestampMixin


class Company(Base, TimestampMixin):
    """Represents an employer or hiring organization."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_pattern: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_catch_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
