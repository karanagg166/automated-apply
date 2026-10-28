"""Public owner-only missing-answer responses, shared with generated API clients."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.ai.schemas import QuestionType

InputStatus = Literal["needs_input", "draft", "approved", "review_required"]


class MissingInputRead(BaseModel):
    id: str
    candidate_profile_id: UUID
    question: str
    question_category: QuestionType
    job_id: UUID | None
    company_name: str | None
    job_description: str | None
    packet_id: UUID | None
    missing_information: list[str]
    reason: str
    required_input_type: Literal["text", "number", "choice", "evidence", "profile_edit"]
    created_at: datetime
    status: InputStatus
    effective_status: InputStatus
    version: int
    profile_version: int
    context_digest: str
    stale: bool
    answer: str | None
    evidence_note: str
    draft_id: UUID | None
    ever_approved: bool = False
    href: str


class MissingInputList(BaseModel):
    requests: list[MissingInputRead]
    offset: int
    limit: int


class MissingInputRevision(BaseModel):
    request_id: str
    candidate_profile_id: UUID
    operation: Literal["edited", "approved_exact_context"]
    version: int
    previous: dict[str, Any]
    recorded_at: datetime


class MissingInputHistory(BaseModel):
    history: list[MissingInputRevision] = Field(default_factory=list)
