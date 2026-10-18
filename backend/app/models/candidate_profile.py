"""Primary candidate record; JSONB on PostgreSQL, JSON on SQLite."""

import uuid
from sqlalchemy import CheckConstraint, Float, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import Base, GUID, TimestampMixin


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint("singleton_key = 'primary'", name="ck_candidate_primary"),
        CheckConstraint("version >= 1", name="ck_candidate_version"),
        CheckConstraint("length(trim(full_name)) BETWEEN 1 AND 200", name="ck_candidate_name"),
        CheckConstraint("length(email) BETWEEN 3 AND 254", name="ck_candidate_email"),
        CheckConstraint("verified_experience_years BETWEEN 0 AND 100", name="ck_candidate_experience"),
        CheckConstraint("summary IS NULL OR length(trim(summary)) BETWEEN 1 AND 4000", name="ck_candidate_summary"),
        {"schema": "job_agent" if Base.schema_name is not None else None},
    )
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    singleton_key: Mapped[str] = mapped_column(String(20), default="primary", unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    github_url: Mapped[str | None] = mapped_column(String(2048))
    portfolio_url: Mapped[str | None] = mapped_column(String(2048))
    personal_website: Mapped[str | None] = mapped_column(String(2048))
    verified_experience_years: Mapped[float | None] = mapped_column(Float)
    verified_skills: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False)
    verified_roles: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False)
    education: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False)
    projects: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False)
    certifications: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    __mapper_args__ = {"version_id_col": version}
