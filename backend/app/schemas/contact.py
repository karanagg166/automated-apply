"""Pydantic schemas for Contact entities and email candidates."""

from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class EmailVerificationStatus(str, Enum):
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    PROVIDER_REPORTED = "provider_reported"
    VERIFIED = "verified"
    INVALID = "invalid"


class EmailCandidate(BaseModel):
    """An email candidate derived mathematically from company patterns."""
    email: str = Field(..., description="Generated candidate email address")
    pattern_used: str = Field(..., description="Pattern identifier, e.g. {first}.{last}@{domain}")
    status: Literal["candidate"] = "candidate"
    confidence_score: float = Field(default=0.40, ge=0.0, le=1.0)
    disclaimer: str = Field(
        default="This is an inferred candidate pattern, NOT a verified mailbox.",
        description="Explicit notice that candidate addresses require verification before outreach",
    )


class ContactBase(BaseModel):
    company_id: UUID = Field(..., description="Associated company UUID")
    full_name: str = Field(..., min_length=1, max_length=255)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    role_title: str = Field(..., min_length=1, max_length=255, description="Professional title / role")
    linkedin_url: str | None = Field(None, description="Public LinkedIn profile URL")
    email: str | None = Field(None, max_length=255)
    email_status: EmailVerificationStatus = Field(default=EmailVerificationStatus.UNKNOWN)
    confidence_score: float = Field(default=0.0, ge=0.0, le=100.0)
    enrichment_source: str | None = Field(
        None,
        max_length=100,
        description="Origin source: cache, pattern_inference, hunter, apollo, serper, signalhire",
    )
    last_verified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    first_name: str | None = None
    last_name: str | None = None
    role_title: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    email_status: EmailVerificationStatus | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=100.0)
    enrichment_source: str | None = None
    last_verified_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class ContactRead(ContactBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
