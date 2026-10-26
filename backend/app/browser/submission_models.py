"""Durable browser execution records attached to the existing application packet.

These tables require the separately reviewed browser extension migration. Importing
models does not install it or enable submission. No second application status exists.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.models.application_packet import (
    ApplicationPacket,
    ApplicationSubmissionEvidence,
)
from backend.app.models.base import GUID, Base

Json = JSON().with_variant(JSONB, "postgresql")


def now():
    return datetime.now(timezone.utc)


class BrowserExecutionBase(DeclarativeBase):
    metadata = MetaData(schema=Base.schema_name)


class BrowserSubmissionGrant(BrowserExecutionBase):
    __tablename__ = "browser_submission_grants"
    __table_args__ = (UniqueConstraint("token_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(ApplicationPacket.id), nullable=False, index=True
    )
    packet_revision: Mapped[int] = mapped_column(nullable=False)
    preview_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization: Mapped[dict] = mapped_column("binding", Json, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )


class BrowserSubmissionAttempt(BrowserExecutionBase):
    __tablename__ = "browser_submission_attempts"
    __table_args__ = (
        UniqueConstraint("packet_id"),
        UniqueConstraint("idempotency_key"),
        UniqueConstraint("grant_id"),
        CheckConstraint(
            "state IN ('dispatched','unknown','verified')",
            name="ck_browser_attempt_state",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(ApplicationPacket.id), nullable=False
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey(BrowserSubmissionGrant.id), nullable=False
    )
    packet_revision: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter: Mapped[str] = mapped_column(String(40), nullable=False)
    destination: Mapped[str] = mapped_column(String(2048), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, nullable=False
    )
    lease_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt: Mapped[dict | None] = mapped_column(Json)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey(ApplicationSubmissionEvidence.id)
    )
    diagnostic: Mapped[str | None] = mapped_column(Text)
