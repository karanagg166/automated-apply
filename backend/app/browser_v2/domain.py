"""Portal-neutral domain DTOs shared by adapters, the store and services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.browser_v2.rules import ApplicantCount


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
    # Phase 8b: required experience as shown by the portal ("0 - 5 years", "4-5 Yrs", "Fresher").
    experience_text: str | None = None
    # Phase 9B: exact posting time (ATS feeds) and hour-precision age ("3 hours ago") when known.
    posted_at: datetime | None = None
    posted_age_hours: float | None = None
