"""Typed portal adapter protocol shared by Naukri and the Phase 6 portals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from backend.app.browser_v2.rules import ApplicantCount
from backend.app.browser_v2.state import ApplicationState


class AuthStatus(StrEnum):
    OK = "OK"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SessionCheck:
    status: AuthStatus
    refreshed: bool = False
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobListing:
    platform: str
    external_job_id: str
    url: str
    title: str | None = None
    company: str | None = None
    posted_text: str | None = None
    posted_age_days: int | None = None
    age_is_lower_bound: bool = False
    applicants: ApplicantCount | None = None


@dataclass(frozen=True)
class JobDetail:
    listing: JobListing
    applicants: ApplicantCount
    posted_age_days: int | None
    already_applied: bool
    apply_mode: str  # direct | external | none | ambiguous
    challenge: str | None = None
    portal_limit: str | None = None
    description: str | None = None  # plain-text JD, bounded (never raw HTML)
    salary_text: str | None = None
    location: str | None = None
    work_mode: str | None = None


@dataclass(frozen=True)
class HitlQuestion:
    kind: str  # CAPTCHA | OTP | AUTH | QUESTION | ERROR
    prompt: str
    options: tuple[str, ...] = ()
    input_kind: str | None = None  # choice | text | file
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyResult:
    state: ApplicationState
    reason: str
    dry_run: bool
    planned_action: str | None = None
    receipt: dict[str, Any] | None = None
    screenshot: str | None = None
    question: HitlQuestion | None = None
    clicked_apply: bool = False
    answers: tuple[dict[str, str], ...] = ()


@runtime_checkable
class PortalAdapter(Protocol):
    platform: str

    async def check_session(self, page: Any) -> SessionCheck: ...

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]: ...

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail: ...

    async def extract_form(self, page: Any) -> dict[str, Any]: ...

    async def detect_portal_limit(self, page: Any) -> str | None: ...

    async def apply_job(self, page: Any, detail: JobDetail, profile: Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        """`hitl_answers` maps question text -> owner answer from resolved HITL rows
        (Telegram/dashboard), used before the cache/LLM tiers on a priority re-run."""
        ...
