"""Owner-only application preparation contracts. No portal credentials or arbitrary metadata."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.ai.schemas import Contract as AnswerContract
from backend.app.ai.schemas import EvidenceReference, Question, WritingStyle
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.services.job_discovery_matcher import DiscoveryMatch


class Contract(AnswerContract):
    @field_validator("created_at", "updated_at", check_fields=False)
    @classmethod
    def utc_timestamps(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


Lifecycle = Literal[
    "created",
    "preparing",
    "needs_input",
    "ready_for_review",
    "reviewed",
    "approved_for_manual_handoff",
    "external_application_opened",
    "user_reported_submitted",
    "provider_confirmed_submitted",
    "submitting",
    "submission_unknown",
    "withdrawn",
    "abandoned",
]
Tracking = Literal[
    "not_applied",
    "applied_manually",
    "applied_verified",
    "application_incomplete",
    "application_rejected",
    "interview_scheduled",
    "offer_received",
    "archived",
]
ReadinessState = Literal[
    "needs_profile",
    "needs_input",
    "needs_resume",
    "needs_review",
    "ready_for_manual_handoff",
    "manual_action_required",
    "completed_by_user",
    "completed_verified",
    "unsupported",
]
FieldCategory = Literal[
    "personal_information",
    "contact_information",
    "professional_profile_url",
    "education",
    "experience",
    "technical_skills",
    "resume_upload",
    "salary",
    "notice_period",
    "work_authorization",
    "project_explanation",
    "motivation",
    "free_text",
    "multiple_choice",
    "yes_no",
    "unknown",
]
FieldType = Literal[
    "text", "textarea", "url", "file", "multiple_choice", "yes_no", "multi_select"
]
ValidationState = Literal[
    "draft_ready",
    "needs_input",
    "file_upload_required",
    "provider_unavailable",
    "validation_failed",
]
ReviewState = Literal["pending", "reviewed"]
IdempotencyKey = Annotated[
    str, Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]


class PlatformCapability(Contract):
    platform: str
    job_discovery: Literal["configured_source_dependent"] = (
        "configured_source_dependent"
    )
    application_preparation: Literal["supported"] = "supported"
    resume_selection: Literal["supported"] = "supported"
    screening_answer_generation: Literal["supported"] = "supported"
    browser_autofill: Literal["not_implemented", "assisted_native_fields"] = (
        "not_implemented"
    )
    automated_submission: Literal["not_authorized_or_verified"] = (
        "not_authorized_or_verified"
    )
    manual_handoff: Literal["supported"] = "supported"
    submission_mode: Literal["manual_handoff"] = "manual_handoff"
    live_verified: Literal[False] = False


class Destination(Contract):
    application_url: str | None = None
    kind: Literal["naukri_hosted", "employer_external", "unknown", "expired_or_invalid"]
    valid: bool = False
    source_confidence: Literal["source_consistent", "source_conflict", "unverified"] = (
        "unverified"
    )
    warnings: list[str] = Field(default_factory=list)


class ResumeOption(Contract):
    resource_id: UUID
    label: str
    url: str | None
    confirmed: bool
    primary: bool
    resource_version: str
    download_path: str | None = None


class ResumeSelection(Contract):
    selected: ResumeOption | None = None
    alternatives: list[ResumeOption] = Field(default_factory=list)
    reason: str
    upload_status: Literal["manual_resume_upload_required"] = (
        "manual_resume_upload_required"
    )


class Provenance(Contract):
    origin: Literal["packet_core", "user_provided"] = "user_provided"
    source: Literal[
        "candidate_profile",
        "candidate_resource",
        "gemini",
        "cohere",
        "ollama",
        "approved_answer",
        "deterministic_extractive",
        "human",
        "missing",
    ] = "missing"
    resolver: Literal[
        "deterministic",
        "grounded_answer_service",
        "human",
        "needs_input",
        "manual_upload",
    ] = "needs_input"
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list, max_length=12
    )
    interview_availability: str | None = Field(None, max_length=300)
    telegram_owner_update: int | None = None
    telegram_question: UUID | None = None
    form_semantic_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    form_page_step: str | None = Field(default=None, max_length=160)
    form_section: str | None = Field(default=None, max_length=160)
    answer_expires_at: datetime | None = None
    answer_draft_id: UUID | None = None
    missing_input_id: str | None = None
    resource_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    error_code: str | None = Field(default=None, max_length=100)


class QuestionInput(Contract):
    question: Question
    category: FieldCategory = "unknown"
    field_type: FieldType = "text"
    required: bool = True
    max_characters: int = Field(default=1500, ge=1, le=10000)
    max_words: int | None = Field(default=None, ge=1, le=1500)
    constraints: str | None = Field(default=None, min_length=1, max_length=1000)
    options: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=50
    )
    writing_style: WritingStyle = "professional"

    @model_validator(mode="after")
    def valid_options(self):
        if len({x.casefold() for x in self.options}) != len(self.options):
            raise ValueError("Options must be unique")
        if (
            self.field_type in {"multiple_choice", "yes_no", "multi_select"}
            and not self.options
        ):
            raise ValueError("Supply the actual form options")
        if self.options and self.field_type not in {
            "multiple_choice",
            "yes_no",
            "multi_select",
        }:
            raise ValueError("Options require a choice field")
        if self.field_type == "multi_select" and any(
            not option.strip() for option in self.options
        ):
            raise ValueError("Multiple-selection options must be nonblank")
        return self


class PacketField(QuestionInput):
    id: UUID
    proposed_answer: str | None = None
    human_answer: str | None = None
    effective_answer: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    validation_status: ValidationState = "needs_input"
    review_status: ReviewState = "pending"
    answer_revision: int = Field(default=1, ge=1)
    requires_review: bool = True
    missing_information: list[str] = Field(default_factory=list)


class PacketSnapshot(Contract):
    preparation_supported: bool = False
    platform: str | None = None
    company_id: UUID | None = None
    company_name: str | None = None
    job_title: str
    source_platform: str
    original_job_url: str
    source_observation_urls: list[str] = Field(default_factory=list)
    destination: Destination
    candidate: CandidateProfileCreate | None = None
    professional_links: dict[Literal["github", "linkedin", "portfolio"], str] = Field(
        default_factory=dict
    )
    resume: ResumeSelection
    match: DiscoveryMatch | None = None
    context_digest: str
    warnings: list[str] = Field(default_factory=list)


class Readiness(Contract):
    state: ReadinessState
    blockers: list[str] = Field(default_factory=list)
    manual_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stale: bool = False


class PacketPreview(Contract):
    job_id: UUID
    candidate_profile_id: UUID | None = None
    candidate_profile_version: int | None = None
    snapshot: PacketSnapshot
    fields: list[PacketField]
    readiness: Readiness
    submission_mode: Literal["manual_handoff"] = "manual_handoff"


class PacketRead(PacketPreview):
    id: UUID
    platform: str
    lifecycle_state: Lifecycle
    tracking_state: Tracking
    revision: int
    approved_revision: int | None = None
    review_status: Literal["pending", "reviewed", "approved", "stale"]
    created_at: datetime
    updated_at: datetime


class PrepareInput(Contract):
    resume_resource_id: UUID | None = None
    questions: list[QuestionInput] = Field(default_factory=list, max_length=50)


class CreatePacket(PrepareInput):
    idempotency_key: IdempotencyKey


class RevisionInput(Contract):
    expected_revision: int = Field(ge=1, le=2147483646)


class AnswerGenerateInput(RevisionInput):
    rewrite: bool = False


class PacketEdit(RevisionInput):
    resume_resource_id: UUID | None = None
    refresh_saved_data: bool = False


class QuestionsAdd(RevisionInput):
    questions: list[QuestionInput] = Field(min_length=1, max_length=50)


class AnswerEdit(RevisionInput):
    answer: str = Field(min_length=1, max_length=10000)


class ReviewInput(RevisionInput):
    action: Literal["review", "approve"] = "review"
    reviewed_field_ids: list[UUID] = Field(default_factory=list, max_length=100)
    confirm_resume: bool = False
    confirm_destination: bool = False


class TrackingInput(RevisionInput):
    tracking_state: Tracking | None = None
    lifecycle_state: (
        Literal["external_application_opened", "withdrawn", "abandoned"] | None
    ) = None
    note: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def change_required(self):
        if self.tracking_state is None and self.lifecycle_state is None:
            raise ValueError("Supply a tracking or lifecycle change")
        return self


class SubmissionInput(RevisionInput):
    idempotency_key: IdempotencyKey
    human_confirmed: Literal[True]
    confirmation: Literal["I submitted this application on the official website"]
    receipt_reference: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("human_confirmed", mode="before")
    @classmethod
    def literal_human_confirmation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Explicit boolean human confirmation is required")
        return value


class ApplicationEventRead(Contract):
    id: UUID
    packet_id: UUID
    event_type: str
    previous_state: Lifecycle | None
    next_state: Lifecycle
    packet_revision: int
    origin: Literal["owner_rest", "system", "local_worker"]
    evidence_id: UUID | None
    note: str | None
    created_at: datetime


class SubmissionRead(Contract):
    id: UUID
    packet_id: UUID
    packet_revision: int
    confirmation_source: Literal["user_reported", "mock_employer"]
    receipt_reference: str | None
    evidence_confidence: Literal["self_reported_unverified", "mock_receipt_verified"]
    human_confirmed: bool
    created_at: datetime


class PacketList(Contract):
    packets: list[PacketRead]
    offset: int
    limit: int


class Handoff(Contract):
    packet_id: UUID
    revision: int
    approved_revision: int
    company: str | None
    job_title: str
    application_url: str
    destination_kind: str
    resume: ResumeSelection
    professional_links: dict[str, str]
    fields: list[PacketField]
    manual_steps: list[str]
    warnings: list[str]
    submission_mode: Literal["manual_handoff"] = "manual_handoff"
    submitted: Literal[False] = False
