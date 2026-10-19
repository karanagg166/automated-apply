"""Startup snapshots and operational diagnostics; existing companies/jobs/runs stay canonical."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base
from backend.app.models.discovery import now


class CompanySourceObservation(Base):
    __tablename__ = "company_source_observations"
    __table_args__ = (
        UniqueConstraint(
            "source", "identity_key", "content_hash", name="uq_company_snapshot"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(100))
    identity_key: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(
        String(50), default="requires_review"
    )


class StartupShortlistEntry(Base):
    __tablename__ = "startup_shortlist_entries"
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderConnectionCheck(Base):
    __tablename__ = "provider_connection_checks"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    configuration_fingerprint: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(50), default="sample_jobs")
    state: Mapped[str] = mapped_column(String(50), default="testing")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    result_count: Mapped[int | None] = mapped_column(Integer)
    schema_valid: Mapped[bool | None] = mapped_column(Boolean)
    is_live: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence_urls: Mapped[list] = mapped_column(JSON, default=list)
    error_category: Mapped[str | None] = mapped_column(String(100))


class ProviderAccessWindow(Base):
    __tablename__ = "provider_access_windows"
    provider: Mapped[str] = mapped_column(String(100), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
