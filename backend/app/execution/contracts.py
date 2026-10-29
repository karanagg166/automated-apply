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


class AutomationPolicy(Contract):
    """Preparation authority only; unsupported employer actions cannot be enabled."""

    profile_version: int = Field(ge=1)
    resume_resource_id: UUID
    resume_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    allowed_roles: list[str] = Field(min_length=1, max_length=25)
    allowed_locations: list[str] = Field(min_length=1, max_length=25)
    excluded_companies: list[str] = Field(default_factory=list, max_length=100)
    experience_min: float = Field(ge=0, le=60, allow_inf_nan=False)
    experience_max: float = Field(ge=0, le=60, allow_inf_nan=False)
    minimum_match_score: int = Field(90, ge=80, le=100)
    interval_seconds: int = Field(21600, ge=900, le=604800)
    max_preparations_per_day: int = Field(5, ge=1, le=25)
    max_posting_age_days: int = Field(14, ge=1, le=30)
    max_applications_per_day: Literal[0] = 0
    permitted_platform: Literal["naukri"] = "naukri"
    permitted_actions: list[Literal["PREPARATION"]] = Field(default_factory=lambda: ["PREPARATION"], min_length=1, max_length=1)
    source: Literal["saved_owner_imports", "gmail_job_alerts"] = "saved_owner_imports"
    gmail_account_id: UUID | None = None
    gmail_policy_version: int | None = Field(None, ge=1)
    telegram_questions: bool = False

    @field_validator("allowed_roles", "allowed_locations", "excluded_companies")
    @classmethod
    def nonblank_bounds(cls, values):
        if any(not v.strip() or len(v) > 200 for v in values):
            raise ValueError("explicit_nonblank_policy_bounds_required")
        return list(dict.fromkeys(v.strip().casefold() for v in values))

    @model_validator(mode="after")
    def experience_bounds(self):
        if self.experience_min > self.experience_max:
            raise ValueError("minimum_exceeds_maximum")
        if self.source == "gmail_job_alerts" and (not self.gmail_account_id or not self.gmail_policy_version):
            raise ValueError("approved_gmail_account_and_policy_version_required")
        return self


class AutomationPolicyUpdate(Contract):
    expected_revision: int = Field(ge=0)
    policy: AutomationPolicy


class AutomationControl(Contract):
    action: Literal["start", "pause", "stop"]
    expected_revision: int = Field(ge=0)


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
    employment_type: Literal["full_time", "part_time", "contract", "internship"] | None = None
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
    alert_candidate_id: UUID | None = None
    application_url: PublicHTTPSURL | None = None
    posting_status: Literal["unknown", "active", "closed", "already_applied"] = "unknown"
    observed_at: datetime | None = None
    valid_through: date | None = None
    posted_at: datetime | None = None

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
        for timestamp in (self.observed_at, self.posted_at):
            if timestamp is not None and (timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc) + timedelta(minutes=5)):
                raise ValueError("observation_requires_nonfuture_timezone_timestamp")
        if self.posting_status != "unknown" and self.observed_at is None:
            raise ValueError("posting_status_requires_owner_observation_time")
        return self


class ImportBatch(Contract):
    jobs: list[ImportJob] = Field(min_length=1, max_length=50)
