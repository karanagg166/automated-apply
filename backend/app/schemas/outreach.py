"""Bounded local draft inputs; no caller-controlled approval or provider IDs."""

from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contact_id: UUID
    job_id: UUID | None = None
    purpose: Literal["job_opportunity", "exploratory"] = "job_opportunity"
    writing_style: Literal[
        "professional", "concise", "friendly", "technical", "founder-focused"
    ] = "professional"
    max_length: int = Field(default=1800, ge=400, le=5000)
    personal_instructions: str | None = Field(default=None, max_length=1000)
    use_llm: bool = True
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )


class DraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    recipient_email: EmailStr | None = None

    @field_validator("subject", "recipient_email")
    @classmethod
    def no_header_injection(cls, value):
        if value and ("\r" in value or "\n" in value):
            raise ValueError("Header fields must be single-line")
        return value

    @model_validator(mode="after")
    def edit_required(self):
        if self.model_fields_set <= {"expected_revision"}:
            raise ValueError("Supply an edit")
        if any(
            getattr(self, k) is None
            for k in self.model_fields_set - {"expected_revision"}
        ):
            raise ValueError("Edits cannot be null")
        return self


class DraftDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
