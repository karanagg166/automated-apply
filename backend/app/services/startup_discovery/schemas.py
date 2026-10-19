"""Evidence-bearing company imports and bounded startup queries."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.discovery import DiscoveryQuery, Text
from backend.app.schemas.normalized_job import NormalizedJob

Band = Literal["1-10", "11-50", "51-200", "201-500", "500+", "unknown"]
Hiring = Literal[
    "hiring_confirmed", "hiring_possible", "hiring_unknown", "not_currently_hiring"
]
Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,100}$")]


class CompanyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    domain: str | None = Field(None, max_length=255)
    source: Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,50}$")]
    source_company_id: Text | None = None
    source_url: PublicHTTPSURL
    permission_evidence_url: PublicHTTPSURL
    observed_at: datetime
    verification_status: Literal[
        "source_reported", "human_confirmed", "requires_review"
    ] = "requires_review"
    historical: bool = False
    employee_count: int | None = Field(None, ge=1, le=10000000, strict=True)
    team_size_band: Band = "unknown"
    location: Text | None = None
    remote_policy: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    industry: Text | None = None
    founding_year: int | None = Field(None, ge=1800, le=2100)
    stage: Text | None = None
    yc_batch: Text | None = None
    description: str | None = Field(None, max_length=4000)
    product_category: Text | None = None
    technology_stack: list[Text] = Field(default_factory=list, max_length=30)
    careers_url: PublicHTTPSURL | None = None
    hiring_statement: Literal["hiring_possible", "not_currently_hiring"] | None = None
    authoritative_statement: bool = False

    _domain = field_validator("domain")(NormalizedJob.domain.__func__)

    @field_validator("observed_at")
    @classmethod
    def timestamp(cls, value):
        if value.tzinfo is None or value > datetime.now(timezone.utc) + timedelta(
            minutes=5
        ):
            raise ValueError("An actual timezone-aware observation time is required")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def consistent(self):
        from backend.app.services.startup_discovery.normalizer import size_band

        if self.employee_count is not None:
            expected = size_band(self.employee_count)
            if self.team_size_band not in ("unknown", expected):
                raise ValueError("Count and band conflict within an observation")
            self.team_size_band = expected
        if (
            self.hiring_statement == "not_currently_hiring"
            and not self.authoritative_statement
        ):
            raise ValueError("An explicit authoritative statement is required")
        return self


class StartupFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_employees: int | None = Field(50, ge=1, le=10000000)
    size_bands: list[Band] = Field(default_factory=list, max_length=6)
    include_unknown_size: bool = True
    locations: list[Text] = Field(default_factory=list, max_length=10)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] | None = None
    roles: list[Text] = Field(default_factory=list, max_length=10)
    skills: list[Text] = Field(default_factory=list, max_length=30)
    stages: list[Text] = Field(default_factory=list, max_length=10)
    yc_batch: Text | None = None
    hiring_status: Hiring | None = None
    freshness_days: int = Field(30, ge=1, le=365)
    minimum_score: float = Field(0, ge=0, le=100, allow_inf_nan=False)
    has_leader_evidence: bool = False
    source: Text | None = None
    use_profile: bool = True
    page: int = Field(1, ge=1, le=250)
    limit: int = Field(20, ge=1, le=100)


class StartupRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["company_first", "job_led"] = "company_first"
    source: Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,50}$")] = "manual"
    idempotency_key: Key
    query: DiscoveryQuery = Field(default_factory=DiscoveryQuery)
    filters: StartupFilters = Field(default_factory=StartupFilters)
    companies: list[CompanyObservation] = Field(default_factory=list, max_length=100)
    permission_confirmed: bool = False
    allow_paid: bool = False

    @model_validator(mode="after")
    def manual_permission(self):
        if self.companies and (
            self.mode != "company_first"
            or self.source != "manual"
            or not self.permission_confirmed
        ):
            raise ValueError(
                "Company imports require manual company-first mode and permission confirmation"
            )
        if len(self.companies) > self.query.limit:
            raise ValueError("Company imports exceed query limit")
        return self


class ShortlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(None, max_length=2000)
    run_id: UUID | None = None
