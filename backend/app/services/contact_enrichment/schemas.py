"""Bounded provider-independent contracts. Confidence categories are evidence labels."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from backend.app.core.urls import PublicHTTPSURL
from backend.app.services.people_discovery.normalizer import normalize_linkedin_url

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
ProviderName = Literal["apollo", "signalhire"]


class State(StrEnum):
    NOT_CONFIGURED = "not_configured"
    AUTHORIZATION_REQUIRED = "authorization_required"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"
    UNSUPPORTED = "unsupported_operation"
    UNCERTAIN = "billing_uncertain"


class Capabilities(BaseModel):
    search_people: bool = False
    enrich_person: bool = True
    get_usage: bool = False
    test_connection: bool = True
    bulk: bool = False
    mailbox_verification: bool = False
    delivery: Literal["synchronous", "asynchronous"] = "synchronous"


class PersonObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Text
    role_title: Text | None = None
    company_domain: Text | None = None
    linkedin_url: str | None = Field(None, max_length=2048)
    email: str | None = Field(None, max_length=255)
    provider_person_id: Text | None = None
    source: Text
    evidence_url: PublicHTTPSURL | None = None
    observed_at: datetime | None = None
    provider_verification_claim: str | None = Field(None, max_length=100)
    evidence_strength: Literal["weak", "moderate", "strong"] = "moderate"
    email_kind: Literal[
        "person_specific", "role_based", "company_general", "inferred"
    ] = "person_specific"
    email_status: Literal[
        "unknown", "candidate", "provider_reported", "verified", "invalid"
    ] = "unknown"
    discovered_person_id: UUID | None = None

    @field_validator("linkedin_url")
    @classmethod
    def profile_url(cls, value):
        return normalize_linkedin_url(value) if value else None


class ContactEnrichmentRequest(BaseModel):
    company_id: UUID
    person_id: UUID | None = None
    full_name: Text | None = None
    company_domain: Text | None = None
    linkedin_url: str | None = Field(None, max_length=2048)
    provider_person_id: Text | None = None
    target_roles: list[Text] = Field(default_factory=list, max_length=20)
    max_people: int = Field(5, ge=1, le=25)
    allow_paid: bool = False
    _profile_url = field_validator("linkedin_url")(
        PersonObservation.profile_url.__func__
    )


class ContactEnrichmentResult(BaseModel):
    status: State
    provider: str
    contacts: list[PersonObservation] = Field(default_factory=list)
    credits_used: int | None = None
    credits_remaining: int | None = None
    provider_run_id: str | None = None
    retry_after_seconds: int | None = None
    errors: list[str] = Field(default_factory=list)


class EnrichInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_roles: list[Text] = Field(default_factory=list, max_length=20)
    max_people: int = Field(5, ge=1, le=25)
    providers: list[ProviderName] = Field(
        default_factory=lambda: ["apollo"], max_length=2
    )
    allow_paid: bool = False
    allow_fallback: bool = False
    include_candidates: bool = False
    idempotency_key: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")] | None
    ) = None

    @field_validator("providers")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate providers")
        return value


class ContactCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Text | None = None
    role_title: Text | None = None
    company_id: UUID | None = None
    email_status: (
        Literal["unknown", "candidate", "provider_reported", "verified", "invalid"]
        | None
    ) = None
    verification_evidence_id: UUID | None = None
    do_not_contact: bool | None = None
    suppression_reason: str | None = Field(None, max_length=1000)
    human_review_notes: str | None = Field(None, max_length=4000)
