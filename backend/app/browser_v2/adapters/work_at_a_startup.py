"""YC Work at a Startup adapter (persistent Brave profile, YC account login).

Startup role discovery -> job page -> "Apply" opens a short note to the founders; the
note comes from the PII-scrubbed LLM composer with a deterministic, facts-only
fallback. Dry-run stops before the Apply click.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from backend.app.browser_v2.adapters.common import (
    InteractivePortalAdapter,
    PortalConfig,
)

ORIGIN = "https://www.workatastartup.com"


class WorkAtAStartupAdapter(InteractivePortalAdapter):
    config = PortalConfig(
        platform="work_at_a_startup", label="YC Work at a Startup",
        hosts=("www.workatastartup.com", "workatastartup.com"),
        home_url=ORIGIN + "/application",
        job_path=r"^/jobs/(\d{2,12})/?$",
        logged_in='a[href*="/application"], a[href*="/logout"], a[href*="/users/sign_out"], '
                  '[class*="avatar" i], a[href*="/profile"]',
        login_hosts=("account.ycombinator.com",),
        apply_text=r"^(?:apply|apply now|apply to (?:this )?(?:job|role))$",
        applied_text=r"^(?:applied|application sent)$",
        confirm_text=r"application sent|applied successfully|you(?:'ve| have) applied|your application (?:has been|was) sent")

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        return f"{ORIGIN}/companies?query={quote_plus(query)}&layout=list-compact&sortBy=created_desc"
