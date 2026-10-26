"""Additive Phase 2A storage; quota reservations commit independently of drafts."""
import uuid
from datetime import datetime

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import GUID, Base, TimestampMixin

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")
PROFILE_FK = f"{Base.schema_name}.candidate_profiles.id" if Base.schema_name else "candidate_profiles.id"
JOB_FK = f"{Base.schema_name}.jobs.id" if Base.schema_name else "jobs.id"


class CandidateResource(Base, TimestampMixin):
    __tablename__ = "candidate_resources"
    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "resource_type", "url", name="uq_candidate_resource_url"),
        CheckConstraint("resource_type IN ('resume','leetcode','codeforces','geeksforgeeks','hackerrank','kaggle','other')", name="ck_additional_resource_type"),
        Index("uq_candidate_resource_primary", "candidate_profile_id", "resource_type", unique=True,
              postgresql_where=text("is_primary"), sqlite_where=text("is_primary = 1")),
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey(PROFILE_FK, ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), default="user", nullable=False)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CandidateEvidence(Base, TimestampMixin):
    __tablename__ = "candidate_evidence"
    __table_args__ = (CheckConstraint("evidence_type IN ('project','experience','achievement','resume_note','other')", name="ck_evidence_type"),)
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey(PROFILE_FK, ondelete="CASCADE"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_description: Mapped[str | None] = mapped_column(String(200))
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    project: Mapped[dict | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"))


class ApplicationAnswerDraft(Base, TimestampMixin):
    __tablename__ = "application_answer_drafts"
    __table_args__ = (CheckConstraint("review_status IN ('draft','reviewed','discarded')", name="ck_answer_review"),)
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey(PROFILE_FK, ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey(JOB_FK, ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    question_category: Mapped[str] = mapped_column(String(40), nullable=False)
    writing_style: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(150))
    evidence_references: Mapped[list] = mapped_column(JSON_TYPE, default=list, nullable=False)
    candidate_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)


class LLMMonthlyUsage(Base, TimestampMixin):
    __tablename__ = "llm_monthly_usage"
    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
