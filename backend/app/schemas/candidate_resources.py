"""User-supplied resources and evidence. Confirmation is always explicit."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from backend.app.ai.schemas import Contract
from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.candidate_profile import LongText, ShortText, VerifiedProject

ResourceType = Literal["resume", "github", "linkedin", "portfolio", "leetcode", "codeforces", "geeksforgeeks", "hackerrank", "kaggle", "other"]
EvidenceType = Literal["project", "experience", "achievement", "resume_note", "other"]


class ResourceWrite(Contract):
    id: UUID | None = None
    resource_type: ResourceType
    label: ShortText
    url: PublicHTTPSURL
    is_primary: bool = False
    source_type: Literal["user", "environment_import"] = "user"
    user_confirmed: bool = False
    expected_profile_version: int | None = Field(default=None, ge=1)


class ResourceRead(Contract):
    id: UUID
    candidate_profile_id: UUID
    resource_type: ResourceType
    label: str
    url: str
    is_primary: bool
    source_type: str
    user_confirmed: bool
    created_at: datetime
    updated_at: datetime


class ResolvedLink(Contract):
    resource_type: ResourceType
    url: str | None = None
    source: str | None = None
    resource_id: UUID | None = None
    user_confirmed: bool = False


class ResourceList(Contract):
    resources: list[ResourceRead]
    resolved_links: list[ResolvedLink]
    offset: int
    limit: int


class EvidenceWrite(Contract):
    evidence_type: EvidenceType
    title: ShortText
    content: LongText
    source_url: PublicHTTPSURL | None = None
    source_description: ShortText | None = None
    user_confirmed: bool = False
    project: VerifiedProject | None = None

    @model_validator(mode="after")
    def project_type(self):
        if self.project is not None and self.evidence_type != "project":
            raise ValueError("Project details require project evidence")
        if self.project and self.project.url:
            TypeAdapter(PublicHTTPSURL).validate_python(self.project.url)
        return self


class EvidencePatch(Contract):
    title: ShortText | None = None
    content: LongText | None = None
    source_url: PublicHTTPSURL | None = None
    source_description: ShortText | None = None
    user_confirmed: bool | None = None
    project: VerifiedProject | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set & {"title", "content", "user_confirmed"}):
            raise ValueError("Supply non-null changed fields")
        return self


class EvidenceRead(EvidenceWrite):
    id: UUID
    candidate_profile_id: UUID
    created_at: datetime
    updated_at: datetime


class EvidenceList(Contract):
    verified: list[EvidenceRead]
    unverified: list[EvidenceRead]
    offset: int
    limit: int
