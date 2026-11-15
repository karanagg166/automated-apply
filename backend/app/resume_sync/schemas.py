"""Typed owner controls. Review cannot be disabled by configuration or API callers."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.ai.schemas import Contract
from backend.app.dashboard.schemas import ResumeConfirm
from backend.app.resume_sync.source import canonical_source
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.schemas.candidate_resources import EvidenceWrite


class SourceSettings(Contract):
    canonical_url: str = Field(max_length=2048)
    expected_generation: int = Field(ge=1)
    sync_enabled: bool = False
    interval_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("canonical_url")
    @classmethod
    def drive_url(cls, value):
        return canonical_source(value)[1]


class SyncNow(Contract):
    expected_generation: int = Field(ge=1)


class ApproveResume(ResumeConfirm):
    expected_generation: int = Field(ge=1)
    expected_profile_version: int | None = Field(default=None, ge=1)
    profile: CandidateProfileCreate
    allow_skill_removals: bool = False
    evidence: list[EvidenceWrite] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def reviewed_evidence(self):
        if any(not item.user_confirmed for item in self.evidence):
            raise ValueError("Every supplied claim requires explicit owner confirmation")
        return self


class ResumeVersionRead(Contract):
    id: UUID
    file_id: str
    canonical_url: str
    file_name: str
    sha256: str
    source_modified_at: datetime | None
    source_etag: str | None
    drive_revision: str | None
    downloaded_at: datetime
    private_resume_id: UUID
    review_status: Literal["pending", "approved"]
    review_cycle: int
    candidate_profile_version: int | None
    approved_profile_version: int | None


class SyncStatus(Contract):
    download_available: Literal[False] = False
    source: Literal["Google Drive"] = "Google Drive"
    canonical_url: str | None
    file_id: str | None
    file_name: str | None
    last_downloaded_at: datetime | None
    source_modified_at: datetime | None
    source_etag: str | None
    drive_revision: str | None
    generation: int
    sync_enabled: bool
    interval_hours: int
    requires_review: Literal[True] = True
    connected: bool
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    last_changed_at: datetime | None
    latest: ResumeVersionRead | None
    active: ResumeVersionRead | None
    history: list[ResumeVersionRead]
    pending_changes: bool
    scheduler_active: bool
    scheduler_message: str
    metadata_note: str = "Public downloads expose Last-Modified/ETag only when provided. Drive revision metadata may be unavailable; checks always verify PDF SHA-256."


class SyncResult(Contract):
    outcome: Literal["pending_review", "unchanged", "failed", "disabled_or_not_due"]
    state: SyncStatus


class FactDifference(Contract):
    category: str
    before: list[str]
    after: list[str]
    added: list[str]
    removed: list[str]
    current_verified: list[str] = Field(default_factory=list)


class ResumeSuggestions(Contract):
    full_name: str
    email: str
    verified_skills: list[str]


class ResumeReviewRead(Contract):
    version: ResumeVersionRead
    expected_generation: int
    expected_profile_version: int | None
    current_profile: CandidateProfileCreate | None
    suggested_identity: ResumeSuggestions
    proposed_profile: CandidateProfileCreate | None
    differences: list[FactDifference]
    text: str
    warnings: list[str]
    stale_packet_count: int
    stale_answer_count: int
