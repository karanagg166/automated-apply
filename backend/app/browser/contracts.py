"""Owner inputs contain no browser handles, selectors, scripts, or filesystem paths."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool

from backend.app.ai.schemas import Contract
from backend.app.schemas.applications import IdempotencyKey, RevisionInput


class PrepareBrowser(Contract):
    application_url: str = Field(min_length=10, max_length=2048)
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    idempotency_key: IdempotencyKey
    resume_resource_id: UUID | None = None


class OpenBrowser(RevisionInput):
    approve_dedicated_profile: StrictBool
    confirm_destination_permission: StrictBool
    confirm_asset_permissions: StrictBool = False
    asset_policy_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class BrowserAction(RevisionInput):
    action: Literal["analyze", "fill", "preview", "take_over", "cancel", "submit"]
    operation_id: UUID | None = None
    confirm_reviewed_values: StrictBool = False
    confirm_page_context: StrictBool = False


class DetectedField(Contract):
    key: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    question: str = Field(max_length=2000)
    kind: str
    accept: str = Field(default="", max_length=200)
    required: bool
    options: list[str] = Field(default_factory=list, max_length=50)
    choices_on_open: bool = False
    max_characters: int = Field(default=1500, ge=1, le=10000)
    supported: bool = False
    manual_reason: str | None = None
    field_id: str | None = None


class StepControl(Contract):
    key: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    label: str = Field(min_length=1, max_length=200)
    supported: bool
