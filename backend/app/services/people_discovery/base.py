from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from backend.app.schemas.discovery import Text
from backend.app.core.job_urls import canonical_job_url

Role = Literal[
    "founder",
    "co-founder",
    "ceo",
    "cto",
    "head of engineering",
    "engineering manager",
    "technical recruiter",
    "talent acquisition",
    "recruiter",
]


class PublicPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, max_length=255)
    linkedin_url: str = Field(max_length=2048)
    evidence_url: str = Field(max_length=2048)
    source: Literal["public_search", "manual"] = "manual"
    verification_status: Literal["source_reported", "requires_review"] = (
        "requires_review"
    )
    evidence_text: str | None = Field(None, max_length=4000)
    outreach_mode: Literal["manual"] = "manual"

    @field_validator("linkedin_url")
    @classmethod
    def linkedin(cls, value):
        from backend.app.services.people_discovery.normalizer import (
            normalize_linkedin_url,
        )

        return normalize_linkedin_url(value)

    @field_validator("evidence_url")
    @classmethod
    def evidence(cls, value):
        return canonical_job_url(value)


class PeopleQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: Text
    company_domain: str | None = Field(None, max_length=255)
    roles: list[Role] = Field(
        default_factory=lambda: ["founder", "cto", "recruiter"],
        min_length=1,
        max_length=9,
    )
    location: Text | None = None
    source: Literal["public_search", "manual", "linkedin"] = "public_search"
    limit: int = Field(10, ge=1, le=20)
    allow_paid: bool = False
    manual_people: list[PublicPerson] = Field(default_factory=list, max_length=20)

    @field_validator("company_domain")
    @classmethod
    def domain(cls, value):
        from backend.app.schemas.normalized_job import NormalizedJob

        return NormalizedJob.domain(value)
