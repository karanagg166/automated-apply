"""Integrated owner-reviewed browser workflows with separate route and approval boundaries."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, SecretStr, StrictBool

from backend.app.ai.schemas import Contract as AssistantContract
from backend.app.browser.contracts import Contract
from backend.app.schemas.applications import IdempotencyKey, RevisionInput

SubmissionState = Literal[
    "prepared",
    "form_inspected",
    "form_filled",
    "awaiting_submission_approval",
    "submitting",
    "submitted",
    "submission_uncertain",
    "manual_required",
    "failed",
]


class SubmissionApproval(Contract):
    nonce: UUID
    review_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    campaign_revision: int = Field(ge=1)
    application_ids: list[UUID] = Field(min_length=1, max_length=1)
    maximum_count: Literal[1] = 1
    scope: Literal["submit_application"] = "submit_application"


class SubmissionEvidence(Contract):
    type: Literal[
        "application_acknowledgment",
        "employer_confirmation_response",
        "known_confirmation_page",
    ]
    destination: str
    timestamp: str
    application_id: str = Field(pattern=r"^fixture-[a-z0-9-]{1,80}$")
    correlation_id: UUID


class Submission(Contract):
    id: UUID = Field(default_factory=uuid4)
    owner: Literal["primary"] = "primary"
    application_id: UUID
    job_id: UUID
    employer_id: UUID
    employer: str
    job_title: str
    plan_id: UUID
    campaign_id: UUID
    campaign_revision: int
    candidate_profile_id: UUID
    candidate_version: int
    context_digest: str
    packet_revision: int
    project_digest: str
    pdf_digest: str | None = None
    document_id: str
    document_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    adapter: Literal["greenhouse", "lever", "google"]
    origin: str
    application_url: str
    request_url: str
    confirmation_url: str
    receipt_url: str
    nonce: UUID = Field(default_factory=uuid4)
    idempotency_key: UUID = Field(default_factory=uuid4)
    expires_at: str
    review_digest: str = ""
    state: SubmissionState = "prepared"
    authorization: dict | None = None
    released: bool = False
    cancelled: bool = False
    fence: int = 0
    lease_until: str | None = None
    dispatch_started_at: str | None = None
    evidence: SubmissionEvidence | None = None
    reason: str | None = None
    revision: int = 0
    command_campaign_ids: list[UUID] = Field(default_factory=list, max_length=20)


class SubmissionPreviewRequest(RevisionInput):
    confirm_page_context: StrictBool


class SubmissionAuthorization(RevisionInput):
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_exact_application: StrictBool
    reviewed_consent_ids: list[str] = Field(default_factory=list, max_length=100)


class SubmitApproved(RevisionInput):
    grant_id: UUID
    grant_token: SecretStr
    idempotency_key: IdempotencyKey


class MockReceipt(AssistantContract):
    status: Literal["accepted"]
    attempt_id: UUID
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    receipt_reference: str = Field(pattern=r"^MOCK-[a-f0-9]{32}$")
    fixture: Literal["automated-apply-employer-v1"]


class MockNarrativeReceipt(MockReceipt):
    fixture: Literal["automated-apply-employer-v2"]


class ConsentAction(RevisionInput):
    field_id: UUID
    checked: StrictBool
    confirm_page_context: StrictBool
