"""Durable source, immutable byte versions and explicit profile reviews."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin


def fk(table: str) -> str:
    return f"{Base.schema_name + '.' if Base.schema_name else ''}{table}.id"


class ResumeDriveSource(Base, TimestampMixin):
    __tablename__ = "resume_drive_sources"
    __table_args__ = (
        CheckConstraint("key = 'primary'", name="ck_resume_source_primary"),
        CheckConstraint("interval_hours BETWEEN 1 AND 168", name="ck_resume_sync_interval"),
    )
    key: Mapped[str] = mapped_column(String(20), primary_key=True, default="primary")
    file_id: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="not_checked", nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(80))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_name: Mapped[str | None] = mapped_column(String(200))
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_etag: Mapped[str | None] = mapped_column(String(500))
    drive_revision: Mapped[str | None] = mapped_column(String(200))
    # History survives a source change; only the latest pointer is reset.
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID)


class DriveResumeVersion(Base, TimestampMixin):
    __tablename__ = "drive_resume_versions"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_drive_resume_bytes"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    file_id: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_etag: Mapped[str | None] = mapped_column(String(500))
    drive_revision: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    private_resume_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey(fk("private_resumes")), unique=True, nullable=False)


class ResumeProfileReview(Base, TimestampMixin):
    __tablename__ = "resume_profile_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved')", name="ck_resume_review_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey(fk("drive_resume_versions")), unique=True, nullable=False)
    base_profile_version: Mapped[int | None] = mapped_column(Integer)
    review_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    review_cycle: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approved_profile_version: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
