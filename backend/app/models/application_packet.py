"""Durable application preparation, separate from job discovery and answer drafts."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def fk(table):
    return f"{Base.schema_name + '.' if Base.schema_name else ''}{table}.id"


class ApplicationPacket(Base, TimestampMixin):
    __tablename__ = "application_packets"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "candidate_profile_id", name="uq_application_packet_candidate_job"
        ),
        CheckConstraint("revision >= 1", name="ck_packet_revision"),
        CheckConstraint(
            "approved_revision IS NULL OR approved_revision = revision",
            name="ck_packet_approval_revision",
        ),
        Index(
            "ix_application_packet_platform_state",
            "platform",
            "lifecycle_state",
            "created_at",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(fk("jobs")), nullable=False
    )
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(fk("candidate_profiles")), nullable=False
    )
    candidate_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # RESTRICT preserves the precise resource behind an audited packet.
    resume_resource_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey(fk("candidate_resources"))
    )
    application_url: Mapped[str | None] = mapped_column(String(2048))
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="created"
    )
    tracking_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="not_applied"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    readiness_state: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)


class ApplicationPacketField(Base, TimestampMixin):
    __tablename__ = "application_packet_fields"
    __table_args__ = (
        UniqueConstraint("packet_id", "position", name="uq_packet_field_position"),
        CheckConstraint("answer_revision >= 1", name="ck_packet_answer_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(fk("application_packets")), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    max_words: Mapped[int | None] = mapped_column(Integer)
    constraints: Mapped[str | None] = mapped_column(String(1000))
    options: Mapped[list] = mapped_column(JSON_TYPE, nullable=False, default=list)
    writing_style: Mapped[str] = mapped_column(String(30), nullable=False)
    proposed_answer: Mapped[str | None] = mapped_column(Text)
    human_answer: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    missing_information: Mapped[list] = mapped_column(
        JSON_TYPE, nullable=False, default=list
    )
    answer_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ApplicationSubmissionEvidence(Base):
    __tablename__ = "application_submission_evidence"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(fk("application_packets")), nullable=False, unique=True
    )
    packet_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmation_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="user_reported"
    )
    receipt_reference: Mapped[str | None] = mapped_column(String(255))
    evidence_confidence: Mapped[str] = mapped_column(
        String(40), nullable=False, default="self_reported_unverified"
    )
    human_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        Index("ix_application_events_packet_revision", "packet_id", "packet_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(fk("application_packets")), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(40))
    next_state: Mapped[str] = mapped_column(String(40), nullable=False)
    packet_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="owner_rest"
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey(fk("application_submission_evidence"))
    )
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
