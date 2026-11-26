"""Instahyre adapter (persistent Brave profile).

Matched opportunities -> job page -> deterministic one-click "Apply"/"Interested" +
modal screening questions (4-tier resolver / HITL) -> confirmation text or applied badge.
Dry-run stops before the Apply click (it may submit at once).
"""

from __future__ import annotations

from urllib.parse import quote_plus

from backend.app.browser_v2.adapters.common import (
    InteractivePortalAdapter,
    PortalConfig,
)

ORIGIN = "https://www.instahyre.com"


class InstahyreAdapter(InteractivePortalAdapter):
    config = PortalConfig(
        platform="instahyre", label="Instahyre", hosts=("www.instahyre.com", "instahyre.com"),
        home_url=ORIGIN + "/candidate/opportunities/?matching=true",
        job_path=r"^/job-(\d{3,12})-[A-Za-z0-9-]*/?$",
        logged_in='a[href*="/candidate/profile"], a[href*="logout"], a[href*="/candidate/opportunities"], '
                  '#candidate-nav, [class*="candidate-nav" i]',
        apply_text=r"^(?:apply|apply now|i'?m interested|interested|express interest)$",
        applied_text=r"^(?:applied|already applied|interest shown|application sent)$",
        confirm_text=r"application (?:has been )?(?:sent|submitted)|applied successfully|successfully applied|"
                     r"interest (?:has been )?(?:sent|shown|registered)|you have applied")

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        return f"{ORIGIN}/candidate/opportunities/?matching=true&search={quote_plus(query)}"
