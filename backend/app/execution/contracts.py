"""Private execution contracts. Modes never grant submission permission."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ImportBatch(Contract):
    jobs: list[ImportJob] = Field(min_length=1, max_length=50)
