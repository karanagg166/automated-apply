"""Durable schedule, fenced source executions and factual match cache."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base
from backend.app.models.discovery import now

Json = JSON().with_variant(JSONB, "postgresql")


class AutomationSchedule(Base):
    __tablename__ = "automation_schedule"
    __table_args__ = (CheckConstraint("key = 'primary'", name="ck_automation_primary"),)
    key: Mapped[str] = mapped_column(String(20), primary_key=True, default="primary")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    configuration: Mapped[dict] = mapped_column(Json, default=dict, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    __table_args__ = (
        UniqueConstraint("request_key", "source", name="uq_automation_request_source"),
        CheckConstraint(
            "state IN ('pending','claimed','running','completed','partial','failed','blocked')",
            name="ck_automation_state",
        ),
        CheckConstraint(
            "trigger_type IN ('manual','scheduled')", name="ck_automation_trigger"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    request_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[dict] = mapped_column(Json, nullable=False)
    fence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[dict] = mapped_column(Json, default=dict, nullable=False)
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("discovery_runs.id")
    )


class AutomationMatch(Base):
    __tablename__ = "automation_matches"
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("jobs.id"), primary_key=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(Json, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )
