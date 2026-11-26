"""Wellfound (AngelList Talent) adapter (persistent Brave profile).

Role discovery -> job page -> "Apply" opens the note modal; the cover note / screening
questions go HITL answer -> profile -> semantic cache -> free LLM -> intro composer.
Cloudflare/DataDome challenges or rate-limit pages isolate only this portal
(AUTH_REQUIRED / CAPTCHA HITL). Dry-run stops before the Apply click.
"""

from __future__ import annotations

import re

from backend.app.browser_v2.adapters.common import (
    InteractivePortalAdapter,
    PortalConfig,
)

ORIGIN = "https://wellfound.com"


class WellfoundAdapter(InteractivePortalAdapter):
    config = PortalConfig(
        platform="wellfound", label="Wellfound", hosts=("wellfound.com", "www.wellfound.com"),
        home_url=ORIGIN + "/jobs",
        job_path=r"^/jobs/(\d{3,12})-[A-Za-z0-9-]*/?$",
        logged_in='a[href*="/jobs/applications"], a[href="/profile"], a[href*="/u/"], [data-test*="ProfileMenu" i], '
                  'a[href*="/logout"]',
        apply_text=r"^(?:apply|apply now)$",
        applied_text=r"^(?:applied|application sent)$",
        confirm_text=r"application sent|applied successfully|your application (?:has been|was) (?:sent|submitted)|"
                     r"thanks for applying",
        limit_text=r"too many (?:applications|requests)|application limit|reached (?:the|your) (?:daily )?limit")

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        role = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "software-engineer"
        return f"{ORIGIN}/role/r/{role}"
