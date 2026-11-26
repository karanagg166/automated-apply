"""Internshala adapter (persistent Brave profile): jobs + internships.

Discovery parses applicant counts ("50 applicants", "Be an early applicant") and posting
age from the cards. "Apply now" opens the application form (cover letter "Why should
you be hired for this role?", availability, assessment questions) which is filled via
HITL answer -> profile -> semantic cache -> free LLM (PII-scrubbed) -> intro composer;
anything unresolved becomes WAITING_FOR_USER. Dry-run stops before the Apply click
(a live dry-run must never risk an unrecorded submission).
"""

from __future__ import annotations

import re

from backend.app.browser_v2.adapters.common import (
    InteractivePortalAdapter,
    PortalConfig,
)

ORIGIN = "https://internshala.com"


def slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "software-development"


class InternshalaAdapter(InteractivePortalAdapter):
    config = PortalConfig(
        platform="internshala", label="Internshala", hosts=("internshala.com", "www.internshala.com"),
        home_url=ORIGIN + "/student/dashboard",
        job_path=r"^/(?:job|internship)/detail/[a-z0-9-]*?(\d{6,})/?$",
        logged_in='a[href*="/student/dashboard"], a[href*="/student/applications"], #profile-dropdown, '
                  '.profile_container, a[href*="logout"]',
        login_paths=("/login", "/registration"),
        apply_text=r"^(?:apply now|apply)$",
        applied_text=r"^(?:applied|already applied)$",
        confirm_text=r"application (?:has been )?submitted|submitted successfully|applied successfully|"
                     r"your application (?:has been|was) (?:sent|submitted)",
        limit_text=r"(?:daily|today'?s?)\s+application\s+limit|reached\s+(?:the|your)\s+(?:daily\s+)?application\s+limit",
        form_page_after_apply=True,
        # Live 2026-11-26: four equivalent "Apply now" CTAs; `.company` also contains the title.
        apply_selector="#apply_now_button",
        company_selector=".company_name, .link_display_like_text")

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        return f"{ORIGIN}/jobs/keywords-{slug(query)}/"
