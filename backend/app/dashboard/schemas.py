"""Bounded owner settings and import results; external delivery stays disabled."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.services.startup_discovery.schemas import StartupFilters


class NotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app: bool = True
    paused: bool = False
    daily_digest: bool = True
    minimum_job_score: int = Field(75, ge=0, le=100)
    minimum_startup_score: int = Field(70, ge=0, le=100)
    automation_failures: bool = True
    quiet_start: int = Field(22, ge=0, le=23)
    quiet_end: int = Field(8, ge=0, le=23)
    timezone: str = Field("Asia/Kolkata", max_length=100)
    browser_push: Literal[False] = False
    telegram: Literal[False] = False
    whatsapp: Literal[False] = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown IANA timezone") from None
        return value


class ResumeImportRead(BaseModel):
    id: UUID
    label: str
    pages: int
    text: str
    suggestions: dict
    origin: Literal["extracted_from_resume"] = "extracted_from_resume"
    confirmed: Literal[False] = False
    warnings: list[str]


class ResumeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_confirmed: Literal[True]
    primary: bool = False
    expected_primary_resource_id: UUID | None = None
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    expected_profile_version: int | None = Field(default=None, ge=1)

    @field_validator("owner_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Explicit owner review is required")
        return value


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    filters: StartupFilters


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    title: str
    body: str
    href: str
    read_at: datetime | None
    created_at: datetime
