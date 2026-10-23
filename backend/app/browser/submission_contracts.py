"""Exact preview, short-lived owner authorization and receipt contracts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, StrictBool

from backend.app.ai.schemas import Contract
from backend.app.schemas.applications import IdempotencyKey, RevisionInput


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


class MockReceipt(Contract):
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
