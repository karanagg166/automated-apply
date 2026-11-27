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
        # Live 2026-11-26: logged-out /jobs is public (Apply buttons visible) with a nav "Log in" -> /login.
        login_form='input[type=password], form[action*="login" i], [class*="login-form" i], '
                   'a[href="/login"], a[href^="/login?"]',
        apply_text=r"^(?:apply|apply now)$",
        # Live 2026-11-26 (Phase 8): top action-bar "Apply" + bottom "Apply now" (two components) -> the
        # action-bar button is the primary control (counted only if it reads Apply).
        apply_selector='[class*="actionBar"] button',
        # Live 2026-11-27: the badge reads "✓  Applied" (check mark + nbsp).
        applied_text=r"^(?:[✓✔]\s*)?(?:applied|application sent)$",
        confirm_text=r"application sent|applied successfully|your application (?:has been|was) (?:sent|submitted)|"
                     r"thanks for applying",
        # NOT apply_opens_form: live 2026-11-27 an "Apply" click alone sent applications (badge
        # "✓ Applied" with no modal), so a missing form after the click stays a fence.
        external_modal_text=r"managed outside of wellfound|apply on (?:the )?(?:company(?:'s)? )?website",
        ineligible_modal_text=r"does not support the locations? or timezones?",
        limit_text=r"too many (?:applications|requests)|application limit|reached (?:the|your) (?:daily )?limit")

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        role = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "software-engineer"
        return f"{ORIGIN}/role/r/{role}"
