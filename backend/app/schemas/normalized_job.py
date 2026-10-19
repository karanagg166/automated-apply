"""Evidence-bearing job normalization, backwards compatible with Phase 1 names."""

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.app.core.job_urls import canonical_job_url, ats_job_url


class NormalizedJob(BaseModel):
    source_name: str = Field(min_length=1, max_length=100)
    source_job_id: str | None = Field(None, max_length=255)
    original_url: str = Field(max_length=2048)
    canonical_url: str | None = Field(None, max_length=2048)
    application_url: str | None = Field(None, max_length=2048)
    company_name: str | None = Field(None, max_length=255)
    company_domain: str | None = Field(None, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=200000)
    location: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    is_remote: bool | None = None
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    employment_type: str | None = Field(None, max_length=50)
    experience_level: str | None = Field(None, max_length=50)
    salary_raw: str | None = Field(None, max_length=1000)
    salary_min: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_max: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_currency: str | None = None
    salary_period: Literal["hour", "day", "week", "month", "year"] | None = None
    equity: str | None = Field(None, max_length=1000)
    skills_required: list[str] = Field(default_factory=list, max_length=100)
    skills_preferred: list[str] = Field(default_factory=list, max_length=100)
    date_posted: datetime | None = None
    first_observed_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_observed_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_provenance: dict[str, Any] = Field(default_factory=dict)
    company_intelligence: dict[str, Any] = Field(default_factory=dict)
    source_verification_status: Literal[
        "observed", "source_reported", "verified", "requires_review"
    ] = "observed"
    quality_flags: list[str] = Field(default_factory=list, max_length=50)
    is_confirmed_current: bool = False
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @field_validator("original_url", "canonical_url", "application_url")
    @classmethod
    def safe_urls(cls, value):
        if value is None:
            return value
        canonical_job_url(
            value
        )  # Preserve original evidence link; canonicalize separately.
        return value

    @field_validator("company_domain")
    @classmethod
    def domain(cls, value):
        if value is not None:
            value = value.lower().strip().rstrip(".")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
                raise ValueError("Company domain must be a hostname")
            canonical_job_url("https://" + value)
        return value

    @field_validator("company_intelligence")
    @classmethod
    def intelligence(cls, value):
        for field in (
            "stage",
            "batch",
            "remote_policy",
            "source",
            "verification_status",
        ):
            if field in value and (
                not isinstance(value[field], str) or len(value[field]) > 200
            ):
                raise ValueError("Invalid observed company intelligence")
        if "technologies" in value and (
            not isinstance(value["technologies"], list)
            or len(value["technologies"]) > 100
            or any(
                not isinstance(item, str) or len(item) > 200
                for item in value["technologies"]
            )
        ):
            raise ValueError("Invalid observed technologies")
        return value

    @field_validator("salary_currency")
    @classmethod
    def currency(cls, value):
        if value is not None and not re.fullmatch(r"[A-Z]{3}|[$€£]", value):
            raise ValueError("Use a currency code or observed currency symbol")
        return value

    @field_validator("remote_type", mode="before")
    @classmethod
    def legacy_remote(cls, value):
        return "unknown" if value in (None, "unspecified") else value

    @field_validator(
        "date_posted", "first_observed_date", "last_observed_date", "retrieved_at"
    )
    @classmethod
    def timestamps(cls, value):
        if value is None:
            return None
        value = (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
        if value < datetime(1990, 1, 1, tzinfo=timezone.utc) or value > datetime.now(
            timezone.utc
        ) + timedelta(days=1):
            raise ValueError("Invalid observation/publication date")
        return value

    @model_validator(mode="after")
    def evidence(self):
        original = canonical_job_url(self.original_url)
        application_identity = ats_job_url(self.application_url)
        if self.canonical_url and canonical_job_url(self.canonical_url) not in {
            original,
            application_identity,
        }:
            raise ValueError(
                "Canonical override requires an observed ATS application URL"
            )
        self.canonical_url = application_identity or original
        if self.remote_type == "unknown" and self.is_remote is True:
            self.remote_type = "remote"
        self.is_remote = {"remote": True, "onsite": False}.get(self.remote_type)
        if not self.company_name:
            self.company_name = None
            if "company_unknown" not in self.quality_flags:
                self.quality_flags.append("company_unknown")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("Salary minimum exceeds maximum")
        if self.last_observed_date < self.first_observed_date:
            # The first observation of a new record cannot precede its supplied last observation.
            self.first_observed_date = self.last_observed_date
        if len(self.model_dump_json().encode()) > 262144:
            raise ValueError("Normalized record exceeds 256 KiB")
        return self
