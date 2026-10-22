"""Stable API and provider contracts; model output cannot set trust metadata."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

QuestionType = Literal["profile_link", "personal_details", "short_text", "project_explanation", "technical_experience", "motivation", "startup_interest", "work_authorization", "compensation", "file_upload", "unknown"]
WritingStyle = Literal["professional", "conversational", "technical", "concise", "founder_focused"]
AnswerStatus = Literal["draft_ready", "needs_input", "file_upload_required", "provider_unavailable", "validation_failed"]
ReviewStatus = Literal["draft", "reviewed", "discarded"]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class EvidenceReference(Contract):
    source_type: Literal["verified_project", "verified_role", "candidate_evidence", "candidate_profile", "candidate_preferences"]
    source_id: str = Field(min_length=1, max_length=100)


class TokenUsage(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ResolveRequest(Contract):
    question: Question


class GenerateRequest(ResolveRequest):
    writing_style: WritingStyle = "professional"
    job_id: UUID | None = None
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_description: str | None = Field(default=None, min_length=1, max_length=10000)
    max_characters: int = Field(default=1500, ge=20, le=10000)
    max_words: int | None = Field(default=None, ge=1, le=1500)
    save_draft: bool = False


class AnswerGenerationResult(Contract):
    question_type: QuestionType
    status: AnswerStatus = "needs_input"
    answer: str | None = None
    writing_style: WritingStyle = "professional"
    used_llm: bool = False
    requires_review: bool = True
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    provider: str | None = None
    model: str | None = None
    usage: TokenUsage | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    resources: list[dict] = Field(default_factory=list)
    draft_id: UUID | None = None
    reused_draft_id: UUID | None = None


class SupportedClaim(Contract):
    text: str = Field(min_length=1, max_length=4000)
    source: EvidenceReference
    quote: str = Field(min_length=1, max_length=4000)


class ModelAnswer(Contract):
    answer: str = Field(min_length=1, max_length=10000)
    evidence_references: list[EvidenceReference] = Field(min_length=1, max_length=12)
    claims: list[SupportedClaim] = Field(min_length=1, max_length=30)


class ProviderAnswer(Contract):
    content: ModelAnswer
    usage: TokenUsage = Field(default_factory=TokenUsage)


class DraftReviewUpdate(Contract):
    review_status: ReviewStatus


class DraftRead(Contract):
    id: UUID
    candidate_profile_id: UUID
    job_id: UUID | None
    question: str
    answer: str
    question_category: QuestionType
    writing_style: WritingStyle
    provider: str | None
    model: str | None
    evidence_references: list[EvidenceReference]
    candidate_profile_version: int
    review_status: ReviewStatus
    stale: bool
    created_at: datetime
    updated_at: datetime
