"""Normalized Job schema for cross-platform ingestion."""

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class NormalizedJob(BaseModel):
    """Unified representation of a job posting discovered from any source."""

    source_name: str = Field(
        ...,
        description="Origin source name, e.g. naukri, instahyre, wellfound, greenhouse, lever, remotive, arbeitnow, hacker_news, gmail_alert",
    )
    source_job_id: str | None = Field(
        None,
        description="Identifier assigned by the original source or platform",
    )
    original_url: str = Field(
        ...,
        description="Direct canonical URL to the job posting",
    )
    company_name: str = Field(
        ...,
        min_length=1,
        description="Name of the hiring company",
    )
    company_domain: str | None = Field(
        None,
        description="Primary web domain of the hiring company (e.g. stripe.com)",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Job title/position name",
    )
    description: str | None = Field(
        None,
        description="Full text or detailed summary of the job description",
    )
    location: str | None = Field(
        None,
        description="Job location, city, state, or country",
    )
    is_remote: bool = Field(
        default=False,
        description="Whether the job supports remote work",
    )
    remote_type: str | None = Field(
        None,
        description="Remote policy: 'remote', 'hybrid', 'onsite', or 'unspecified'",
    )
    employment_type: str | None = Field(
        None,
        description="Employment arrangement: 'full_time', 'part_time', 'contract', 'internship'",
    )
    experience_level: str | None = Field(
        None,
        description="Seniority level, e.g. 'entry', 'junior', 'mid', 'senior', 'lead'",
    )
    salary_raw: str | None = Field(
        None,
        description="Raw unparsed salary string from the listing",
    )
    salary_min: float | None = Field(
        None,
        description="Parsed lower bound of compensation",
    )
    salary_max: float | None = Field(
        None,
        description="Parsed upper bound of compensation",
    )
    salary_currency: str | None = Field(
        None,
        description="Currency code for salary, e.g. 'USD', 'INR', 'EUR'",
    )
    skills_required: list[str] = Field(
        default_factory=list,
        description="List of detected technical skill keywords",
    )
    application_url: str | None = Field(
        None,
        description="Direct application or ATS URL if different from listing URL",
    )
    date_posted: datetime | None = Field(
        None,
        description="Date when the posting was first published on the platform",
    )
    last_observed_date: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Most recent timestamp this listing was observed live",
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when our system fetched this record",
    )
    data_provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance audit trail (adapter used, actor name, query params, raw hashes)",
    )
    is_confirmed_current: bool = Field(
        default=False,
        description="True if verified as currently active/open on source; False if merely recently observed",
    )

    model_config = ConfigDict(extra="ignore")
