"""Bounded discovery inputs and explicit outcomes."""

from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from backend.app.schemas.normalized_job import NormalizedJob

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class DiscoveryStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    PARTIAL = "partial"
    UNAVAILABLE = "source_unavailable"
    MISSING_CREDENTIALS = "missing_credentials"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED = "unsupported_operation"
    AUTH_REQUIRED = "authentication_required"
    UPSTREAM_ERROR = "upstream_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CONFIGURATION_REQUIRED = "configuration_required"
    MANUAL_INPUT_REQUIRED = "manual_input_required"


class DiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[Text] = Field(default_factory=list, max_length=10)
    locations: list[Text] = Field(default_factory=list, max_length=10)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] | None = None
    employment_types: list[
        Literal["full_time", "part_time", "contract", "internship"]
    ] = Field(default_factory=list, max_length=4)
    page: int = Field(1, ge=1, le=100)
    limit: int = Field(20, ge=1, le=100)
    max_age_days: int | None = Field(None, ge=1, le=3650)


class DiscoveryResult(BaseModel):
    source: str
    jobs: list[NormalizedJob] = Field(default_factory=list)
    status: DiscoveryStatus
    errors: list[str] = Field(default_factory=list)
    rejected_count: int = 0
    next_cursor: str | None = None
    provider_run_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class DiscoveryError(ValueError):
    def __init__(self, status: DiscoveryStatus, message: str):
        self.status = status
        super().__init__(message)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,50}$")]
    query: DiscoveryQuery = Field(default_factory=DiscoveryQuery)
    idempotency_key: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")] | None
    ) = None
    allow_paid: bool = False
    use_profile: bool = True
    manual_jobs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
