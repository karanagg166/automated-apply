"""Milestone 2 contracts: application proof receipt, owner reconciliation and the ATS watchlist."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.browser_v2.schemas.applications import ApplicationRead

WatchPlatform = Literal["greenhouse", "lever", "ashby", "smartrecruiters"]


class ProofTiming(BaseModel):
    posted_at: datetime | None = None
    discovered_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    first_mover_lag_seconds: int | None = None


class ProofAnswer(BaseModel):
    question: str
    answer: str
    source: str | None = None
    tier_label: str = Field(description="Tier 1 Fact | Tier 2 Exact | Tier 3 Semantic 0.96 | Tier 4 LLM | "
                                        "HITL Human | Resume | Composer | Skipped | Unknown")
    similarity: float | None = None
    cache_entry_id: str | None = None


class ProofMailEvent(BaseModel):
    kind: str
    subject: str | None = None
    sender: str | None = None
    received_at: datetime | None = None


class ProofDraft(BaseModel):
    id: str
    status: str
    recipient_email: str | None = None
    created_at: datetime | None = None


class ApplicationProof(BaseModel):
    application: ApplicationRead
    timing: ProofTiming
    answers: list[ProofAnswer] = Field(default_factory=list)
    resume_variant_used: str | None = None
    screenshot: str | None = Field(default=None, description="Screenshot file name only (never a path)")
    mail_events: list[ProofMailEvent] = Field(default_factory=list)
    outreach_draft: ProofDraft | None = None
    email_verified: bool = False
    confirmed_at: datetime | None = None
    needs_reconciliation: bool = False


class ReconcileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm_applied", "release_not_submitted"]
    confirm: str = Field(default="", max_length=20,
                         description='release_not_submitted requires "RELEASE" (the job becomes apply-eligible again)')


class WatcherRow(BaseModel):
    platform: WatchPlatform
    slug: str
    active: bool
    board_url: str
    last_polled_at: datetime | None = None
    last_status: int | None = None
    jobs_found: int | None = Field(default=None, description="Postings known on the last poll (seen ids)")


class WatcherUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: WatchPlatform
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    active: bool = True


class ProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=3, max_length=2048,
                        description="Careers / ATS board URL (https) or 'platform:slug' (e.g. greenhouse:stripe)")


class ProbeSample(BaseModel):
    title: str
    location: str | None = None
    url: str | None = None
    passes: bool
    reasons: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    platform: WatchPlatform
    slug: str
    board_url: str
    job_count: int
    matched_count: int
    sample: list[ProbeSample] = Field(default_factory=list)
    already_watched: bool = False
