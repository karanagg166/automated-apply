"""Private execution contracts. Modes never grant submission permission."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.core.urls import PublicHTTPSURL

Mode = Literal["OFF", "ON_DEMAND", "WATCH_AND_NOTIFY", "AUTO_APPLY_WHEN_AUTHORIZED"]
State = Literal[
    "DISCOVERED",
    "MATCHED",
    "ELIGIBLE",
    "PREPARING",
    "FILLING",
    "NEEDS_INPUT",
    "READY_FOR_REVIEW",
    "SUBMITTING",
    "SUBMITTED_CONFIRMED",
    "PAUSED",
    "REJECTED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "SUBMISSION_UNKNOWN",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Configuration(Contract):
    mode: Mode = "ON_DEMAND"
    interval_seconds: int = Field(21600, ge=900, le=604800)
    # Source rights and destination/submission authority are separate. Naukri has
    # no demonstrated submission contract, so nonempty grants are refused.
    source: Literal["saved_owner_imports"] = "saved_owner_imports"
    destinations: list[str] = Field(default_factory=list, max_length=10)
    submission_permission: bool = False


class Start(Contract):
    job_ids: list[UUID] = Field(min_length=1, max_length=25)


class Control(Contract):
    action: Literal["pause", "resume", "cancel"]
    expected_revision: int = Field(ge=1)


class QuestionAnswer(Contract):
    expected_revision: int = Field(ge=1, strict=True)
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator("answer")
    @classmethod
    def nonblank_answer(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("answer_required")
        return value


class ImportJob(Contract):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=255)
    employer: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=30000)
    location: str | None = Field(None, max_length=255)
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    preferred_skills: list[str] = Field(default_factory=list, max_length=50)
    experience_min: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    experience_max: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    experience_requirement: Literal["required", "preferred", "unknown"] = "unknown"
    salary_min: float | None = Field(None, ge=0, allow_inf_nan=False)
    salary_max: float | None = Field(None, ge=0, allow_inf_nan=False)
    salary_currency: str | None = Field(None, max_length=3)
    salary_period: Literal["year", "month"] | None = None
    provenance: Literal["owner_url", "owner_job_alert"] = "owner_url"
    message_reference: str | None = Field(None, max_length=200)
    application_url: PublicHTTPSURL | None = None
    posting_status: Literal["unknown", "active", "closed", "already_applied"] = "unknown"
    observed_at: datetime | None = None
    valid_through: date | None = None

    @field_validator("title", "employer")
    @classmethod
    def nonblank_listing_text(cls, value):
        if not value.strip():
            raise ValueError("listing_text_required")
        return value.strip()

    @model_validator(mode="after")
    def reviewed_criteria(self):
        for lower, upper in ((self.experience_min, self.experience_max), (self.salary_min, self.salary_max)):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("minimum_exceeds_maximum")
        if self.observed_at is not None:
            if self.observed_at.tzinfo is None or self.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError("observation_requires_nonfuture_timezone_timestamp")
        if self.posting_status != "unknown" and self.observed_at is None:
            raise ValueError("posting_status_requires_owner_observation_time")
        return self


class ImportBatch(Contract):
    jobs: list[ImportJob] = Field(min_length=1, max_length=50)
