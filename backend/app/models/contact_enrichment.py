"""Additive contact evidence, identity, run and durable lookup claims."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base
from backend.app.models.discovery import now


class ContactEnrichmentRun(Base):
    __tablename__ = "contact_enrichment_runs"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    request_hash: Mapped[str] = mapped_column(String(64))
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    provider_plan: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(50), default="running")
    contact_ids: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)


class ContactEvidence(Base):
    __tablename__ = "contact_evidence"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(100))
    evidence_type: Mapped[str] = mapped_column(String(50))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    observed_role: Mapped[str | None] = mapped_column(String(255))
    observed_company: Mapped[str | None] = mapped_column(String(255))
    provider_verification_claim: Mapped[str | None] = mapped_column(String(100))
    strength: Mapped[str] = mapped_column(String(20), default="moderate")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ContactIdentity(Base):
    __tablename__ = "contact_identities"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "namespace", "identity_key", name="uq_contact_identity"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(100))
    identity_key: Mapped[str] = mapped_column(String(2048))
    discovered_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("discovered_company_people.id", ondelete="SET NULL")
    )


class ContactLookup(Base):
    __tablename__ = "contact_provider_lookups"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "provider", "identity_key", name="uq_contact_lookup"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("companies.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    identity_key: Mapped[str] = mapped_column(String(64))
    reservation_id: Mapped[str] = mapped_column(String(100), unique=True)
    state: Mapped[str] = mapped_column(String(50), default="running")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
