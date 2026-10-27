"""Integrated owner-reviewed browser workflows with separate route and approval boundaries."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.app.ai.schemas import Contract as AssistantContract
from backend.app.schemas.applications import IdempotencyKey, RevisionInput


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, validate_assignment=True
    )


Text = Annotated[str, Field(max_length=160)]
Kind = Literal[
    "text",
    "textarea",
    "email",
    "tel",
    "url",
    "number",
    "select",
    "radio",
    "checkbox",
    "file",
]


class FormField(Contract):
    field_id: str = Field(pattern=r"^f[0-9]{1,3}$")
    kind: Kind
    label: Text
    group_label: Text | None = None
    required: bool = False
    options: list[Text] = Field(default_factory=list, max_length=20)
    max_length: int = Field(default=1500, ge=1, le=4000)
    invalid: bool = False


class Inspection(Contract):
    version: Literal[1] = 1
    document_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    url: str = Field(min_length=1, max_length=2048)
    fields: list[FormField] = Field(default_factory=list, max_length=24)
    state: Literal[
        "ready", "login_required", "manual_required", "unsupported", "validation_errors"
    ] = "ready"
    has_next: bool = False
    has_submit: bool = False

    @model_validator(mode="after")
    def unique_fields(self):
        if len({f.field_id for f in self.fields}) != len(self.fields):
            raise ValueError("duplicate_field_identifier")
        return self


class FillAction(Contract):
    job_id: UUID
    application_id: UUID
    target_url: str
    field_id: str
    kind: Kind
    value: str | None = Field(default=None, max_length=4000)
    safe_reference: str | None = None
    evidence: list[str] = Field(default_factory=list, max_length=12)
    candidate_version: int
    project_version: str | None = None
    requires_review: bool = False
    needs_input: bool = True
    missing_input_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    missing_input_version: int | None = Field(default=None, ge=1)


class FillPlan(Contract):
    version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    application_id: UUID
    job_id: UUID
    mode: Literal["manual_extension", "local_automation"]
    target_url: str
    inspection: Inspection
    context_digest: str
    packet_revision: int
    project_digest: str
    actions: list[FillAction] = Field(default_factory=list, max_length=24)
    approved_fields: list[str] = Field(default_factory=list, max_length=24)
    expires_at: str
    state: Literal["preview", "authorized", "consumed", "finished"] = "preview"


class Review(Contract):
    field_ids: list[str] = Field(max_length=24)


class FieldResult(Contract):
    field_id: str = Field(pattern=r"^f[0-9]{1,3}$")
    status: Literal["filled", "failed", "needs_input", "validation_error", "untouched"]


class FillReceipt(Contract):
    plan_id: UUID
    results: list[FieldResult] = Field(max_length=24)
    state: Literal["form_filled", "needs_input", "manual_required", "failed"]
    submitted: Literal[False] = False


class PrepareBrowser(AssistantContract):
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


class DetectedField(AssistantContract):
    key: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    question: str = Field(max_length=2000)
    kind: str
    accept: str = Field(default="", max_length=200)
    required: bool
    options: list[str] = Field(default_factory=list, max_length=50)
    choices_on_open: bool = False
    options_binding: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    max_characters: int = Field(default=1500, ge=1, le=10000)
    supported: bool = False
    manual_reason: str | None = None
    field_id: str | None = None


class StepControl(AssistantContract):
    key: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    label: str = Field(min_length=1, max_length=200)
    supported: bool
