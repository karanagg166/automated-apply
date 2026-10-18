"""Durable discovery audit, provenance, public people evidence and budget ledger."""

import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import Base, GUID


def now():
    return datetime.now(timezone.utc)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    query_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="running")
    rankings: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_run_id: Mapped[str | None] = mapped_column(String(255))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)


class JobSourceObservation(Base):
    __tablename__ = "job_source_observations"
    __table_args__ = (
        UniqueConstraint("source", "identity_key", name="uq_observation_identity"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(100))
    identity_key: Mapped[str] = mapped_column(String(64))
    source_job_id: Mapped[str | None] = mapped_column(String(255))
    original_url: Mapped[str] = mapped_column(Text)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(50), default="observed")


class DiscoveredPerson(Base):
    __tablename__ = "discovered_company_people"
    __table_args__ = (
        UniqueConstraint("company_id", "linkedin_url", name="uq_company_person_url"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    verification_status: Mapped[str] = mapped_column(String(50))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class DiscoveryMonthlyBudget(Base):
    __tablename__ = "discovery_monthly_budgets"
    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    reserved: Mapped[float] = mapped_column(Numeric(16, 6), default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryReservation(Base):
    __tablename__ = "discovery_budget_reservations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    month: Mapped[str] = mapped_column(String(7))
    reserved: Mapped[float] = mapped_column(Numeric(16, 6))
    provider_run_id: Mapped[str | None] = mapped_column(String(255))
    reported_actual: Mapped[float | None] = mapped_column(Numeric(16, 6))
    state: Mapped[str] = mapped_column(String(50), default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
