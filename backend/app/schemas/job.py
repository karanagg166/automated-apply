"""Pydantic schemas for Job entities."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    REVIEWED = "reviewed"
    SHORTLISTED = "shortlisted"
    APPLIED = "applied"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class JobBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Job position title")
    job_url: str = Field(..., description="Canonical or posting URL")
    source_platform: str = Field(
        ...,
        max_length=100,
        description="Source platform, e.g. gmail_alert, linkedin, greenhouse, lever, manual",
    )
    company_id: UUID | None = Field(None, description="Associated company UUID")
    location: str | None = Field(None, max_length=255)
    is_remote: bool = Field(default=False)
    experience_level: str | None = Field(None, max_length=50)
    salary_range: str | None = Field(None, max_length=100)
    skills_required: list[str] = Field(default_factory=list)
    description: str | None = None
    match_score: float | None = Field(None, ge=0.0, le=100.0, description="Explainable match score 0-100")
    match_explanation: str | None = Field(None, description="Detailed rationale for the match score")
    status: JobStatus = Field(default=JobStatus.DISCOVERED)
    date_posted: datetime | None = None


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    location: str | None = None
    is_remote: bool | None = None
    experience_level: str | None = None
    salary_range: str | None = None
    skills_required: list[str] | None = None
    description: str | None = None
    match_score: float | None = Field(None, ge=0.0, le=100.0)
    match_explanation: str | None = None
    status: JobStatus | None = None
    date_posted: datetime | None = None


class JobRead(JobBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
