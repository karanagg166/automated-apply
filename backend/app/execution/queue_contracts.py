"""Dashboard-owned background queue policy; facts remain in the verified profile."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from backend.app.core.urls import PublicHTTPSURL
from backend.app.execution.contracts import Contract

Platform = Literal["naukri"]  # Extend only when an executable adapter is delivered.
Stage = Literal[
    "DISCOVERED", "MATCHED", "ELIGIBLE", "PREPARING", "READY_TO_APPLY",
    "APPLYING", "QUESTIONS", "RESUME_ATTACHMENT", "VERIFYING", "SUBMITTED_RECORDED",
    "NEEDS_INPUT", "PAUSED", "BLOCKED_PLATFORM", "FAILED_RETRYABLE", "FAILED_FINAL",
    "SUBMISSION_UNKNOWN", "SUBMITTED_CONFIRMED", "SKIPPED",
]


class QueueLimits(Contract):
    daily_cap: int = Field(80, ge=1, le=100)
    max_job_age_days: int = Field(2, ge=1, le=30)
    # At/above this threshold is excluded, including the owner's 10,000 example.
    applicant_limit: int | None = Field(10_000, ge=1, le=10_000_000)
    unknown_applicants: Literal["needs_review", "skip", "allow_lower_bound", "allow"] = "needs_review"
    minimum_match_score: int = Field(80, ge=50, le=100)


class QueuePreferences(Contract):
    roles: list[str] = Field(default_factory=list, max_length=25)
    locations: list[str] = Field(default_factory=list, max_length=25)
    experience_min: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    experience_max: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    minimum_salary: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    maximum_salary: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_currency: str = Field("INR", pattern=r"^[A-Z]{3}$")
    salary_period: Literal["year", "month"] = "year"
    excluded_companies: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("roles", "locations", "excluded_companies")
    @classmethod
    def labels(cls, values):
        if any(not x.strip() or len(x) > 200 for x in values):
            raise ValueError("explicit_nonblank_preference_required")
        return list(dict.fromkeys(x.strip() for x in values))

    @model_validator(mode="after")
    def ranges(self):
        for lower, upper in ((self.experience_min, self.experience_max),
                             (self.minimum_salary, self.maximum_salary)):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("minimum_exceeds_maximum")
        return self


class PlatformQueuePolicy(Contract):
    enabled: bool = False
    sources: list[Literal["approved_gmail_alerts", "saved_verified_job", "naukri_ui_search"]] = Field(
        default_factory=lambda: ["approved_gmail_alerts", "saved_verified_job", "naukri_ui_search"], max_length=3,
    )
    mode: Literal["PREPARE_ONLY", "SUPERVISED", "AUTOMATIC"] = "PREPARE_ONLY"
    owner_submission_authorized: bool = False
    cap_mode: Literal["global", "custom"] = "global"
    age_mode: Literal["global", "custom"] = "global"
    applicants_mode: Literal["global", "custom"] = "global"
    preferences_mode: Literal["global", "custom"] = "global"
    limits: QueueLimits = Field(default_factory=QueueLimits)
    preferences: QueuePreferences = Field(default_factory=QueuePreferences)
    discovery_interval_seconds: int = Field(300, ge=60, le=86400)
    # First actual validation is deliberately below the standing daily cap.
    supervised_submission_cap: int = Field(1, ge=1, le=5)
    hourly_submission_cap: int = Field(5, ge=1, le=20)
    notify_telegram: bool = False


class QueuePolicy(Contract):
    global_limits: QueueLimits = Field(default_factory=QueueLimits)
    platforms: dict[Platform, PlatformQueuePolicy] = Field(
        default_factory=lambda: {"naukri": PlatformQueuePolicy()}
    )
    day_timezone: str = "Asia/Kolkata"
    concurrency: Literal[1] = 1
    max_pending: int = Field(200, ge=1, le=500)
    background_only: Literal[True] = True
    notify_submitted: bool = True

    @model_validator(mode="after")
    def active_adapter_required(self):
        if "naukri" not in self.platforms:
            raise ValueError("naukri_platform_configuration_required")
        return self

    @field_validator("day_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("valid_iana_timezone_required") from None
        return value


class QueuePolicyUpdate(Contract):
    expected_revision: int = Field(ge=0)
    policy: QueuePolicy


class QueueControl(Contract):
    expected_revision: int = Field(ge=0)
    action: Literal["start", "pause", "stop"]


class ObservedNaukriJob(Contract):
    requisition: str = Field(pattern=r"^[0-9]{10,20}$")
    title: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    posting_recruiter: str | None = Field(None, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=20000)
    skills: list[str] = Field(min_length=1, max_length=50)
    experience_min: float = Field(ge=0, le=60, allow_inf_nan=False)
    experience_max: float = Field(ge=0, le=60, allow_inf_nan=False)
    posted_at: datetime | None = None
    posted_date: date | None = None
    applicants_min: int | None = Field(None, ge=0, le=10_000_000)
    applicants_max: int | None = Field(None, ge=0, le=10_000_000)
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    employment_type: Literal["full_time", "part_time", "contract", "internship"] | None = None
    salary_min: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_max: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    salary_period: Literal["year", "month"] | None = None
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("title", "company", "location", "description")
    @classmethod
    def nonblank_facts(cls, value):
        if not value.strip():
            raise ValueError("nonblank_provider_fact_required")
        return value.strip()

    @field_validator("skills")
    @classmethod
    def bounded_skills(cls, values):
        if any(not v.strip() or len(v) > 200 for v in values):
            raise ValueError("bounded_provider_skills_required")
        return list(dict.fromkeys(v.strip() for v in values))

    @model_validator(mode="after")
    def factual_bounds(self):
        if self.posted_at is not None and (self.posted_at.tzinfo is None or self.posted_at > datetime.now(timezone.utc) + timedelta(minutes=5)):
            raise ValueError("nonfuture_timezone_posting_timestamp_required")
        if self.posted_at is not None and self.posted_date is not None:
            raise ValueError("posting_precision_must_be_unambiguous")
        if self.posted_date is not None and self.posted_date > datetime.now(timezone.utc).date() + timedelta(days=1):
            raise ValueError("nonfuture_posting_date_required")
        for lower, upper in ((self.experience_min, self.experience_max),
                             (self.applicants_min, self.applicants_max),
                             (self.salary_min, self.salary_max)):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("invalid_provider_bounds")
        return self


class NaukriExecutionObservation(Contract):
    state: Literal["PROFILE_VERIFIED", "NOT_APPLIED", "APPLIED", "CLICKED", "APPLICATION_SENT", "QUESTIONNAIRE", "PROFILE_OBSERVED", "PROFILE_SAVE_ATTEMPTED", "PROFILE_SKILLS_PREPARED"]
    document_id: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    account_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    resume_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    resume_bytes: int | None = Field(None, ge=1, le=2_000_000)
    title: str | None = Field(None, min_length=1, max_length=255)
    company: str | None = Field(None, min_length=1, max_length=255)
    control_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    profile_fields: dict[str, str | list | dict | int | None] = Field(default_factory=dict, max_length=18)

    @field_validator("profile_fields")
    @classmethod
    def supported_profile_fields(cls, values):
        import json

        from backend.app.execution.profile_sync import FIELDS

        if set(values) - set(FIELDS) or len(json.dumps(values).encode()) > 65536:
            raise ValueError("bounded_supported_profile_fields_required")
        return values


class NaukriQuestionnaire(Contract):
    document_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    step_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    question: str = Field(min_length=1, max_length=2000)
    answer_kind: Literal["choice", "text", "file"]
    options: list[str] = Field(default_factory=list, max_length=50)
    max_characters: int = Field(default=4000, ge=1, le=4000)

    @model_validator(mode="after")
    def actual_options(self):
        if any(not s.strip() or len(s) > 160 for s in self.options) or len(set(self.options)) != len(self.options):
            raise ValueError("unambiguous_questionnaire_options_required")
        if self.answer_kind == "choice" and not self.options:
            raise ValueError("questionnaire_options_required")
        return self


class NaukriWorkReport(Contract):
    kind: Literal["job_facts", "application_view", "source_candidates", "needs_input", "failed", "execution_observation", "questionnaire", "questionnaire_answer_attempted"]
    observed_url: PublicHTTPSURL | None = None
    requisition: str | None = Field(None, pattern=r"^[0-9]{10,20}$")
    stage: Literal["ALREADY_APPLIED"] | None = None
    job: ObservedNaukriJob | None = None
    execution: NaukriExecutionObservation | None = None
    candidates: list[PublicHTTPSURL] = Field(default_factory=list, max_length=20)
    questionnaire: NaukriQuestionnaire | None = None
    document_id: str | None = Field(None, pattern=r"^[a-f0-9-]{36}$")
    step_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    submitted: Literal[False] = False
    reason: str | None = Field(None, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_]+$")
