"""Pydantic schemas for Company entities."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Official company name")
    domain: str | None = Field(None, max_length=255, description="Company root domain (e.g. stripe.com)")
    linkedin_url: str | None = Field(None, description="Public LinkedIn company profile URL")
    email_pattern: str | None = Field(
        None,
        max_length=100,
        description="Observed email pattern, e.g. {first}.{last}@{domain}",
    )
    is_catch_all: bool = Field(default=False, description="Whether the domain mail server is catch-all")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Supplementary company attributes")


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    domain: str | None = Field(None, max_length=255)
    linkedin_url: str | None = None
    email_pattern: str | None = None
    is_catch_all: bool | None = None
    metadata: dict[str, Any] | None = None


class CompanyRead(CompanyBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
