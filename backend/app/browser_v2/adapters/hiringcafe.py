"""HiringCafe adapter: persistent-Brave search-card discovery + employer ATS handoff.

HiringCafe aggregates postings straight from employer ATSs, so it never hosts an
application itself: Greenhouse/Lever "Apply" links are filled by the shared hosted-form
filler; any other employer site is `external_unsupported_ats:<host>` (FILTERED_OUT).
Search needs no login; only a bot challenge pauses the portal.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlsplit

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    HitlQuestion,
    JobDetail,
    SessionCheck,
)
from backend.app.browser_v2.adapters.common import (
    SUPPORTED_ATS,
    HostedAtsApplier,
    InteractivePortalAdapter,
    PortalConfig,
)
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.state import ApplicationState, guard_apply

S = ApplicationState
ORIGIN = "https://hiring.cafe"


class HiringCafeAdapter(InteractivePortalAdapter):
    config = PortalConfig(
        platform="hiringcafe", label="HiringCafe", hosts=("hiring.cafe", "www.hiring.cafe", "hiringcafe.com",
                                                          "www.hiringcafe.com"),
        home_url=ORIGIN + "/", job_path=r"^/(?:viewjob|job)/([A-Za-z0-9_-]{4,120})/?$",
        logged_in="body", apply_text=r"^(?:apply|apply now|apply on company site|apply directly)$",
        external_text=r"^(?:apply|apply now|apply on company site|apply directly|view on company site)$")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.applier = HostedAtsApplier(self.filler, receipts_root=self.receipts_root)

    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        state: dict[str, Any] = {"searchQuery": " ".join(query.split())[:100]}
        if job_age_days:
            state["dateFetchedPastNDays"] = max(1, min(job_age_days, 61))
        return f"{ORIGIN}/?searchState={quote(json.dumps(state, separators=(',', ':')))}"

    async def check_session(self, page: Any) -> SessionCheck:
        await self._goto(page, self.config.home_url)
        probe = await self._probe(page)
        if probe.get("challenge"):
            return SessionCheck(AuthStatus.AUTH_REQUIRED, reason="challenge")
        return SessionCheck(AuthStatus.OK, details={"login": "not_required_for_search"})

    async def inspect_job(self, page: Any, listing: Any) -> JobDetail:
        detail = await super().inspect_job(page, listing)
        # Every HiringCafe "Apply" leaves to the employer: treat the link as the application.
        if detail.apply_mode in ("direct", "external") and detail.apply_url is None:
            links = await page.evaluate(
                "() => [...document.querySelectorAll('a[href]')].filter(a => /apply/i.test(a.innerText || ''))"
                ".map(a => a.href).filter(h => /^https:\\/\\//.test(h)).slice(0, 3)")
            external = [h for h in links if (urlsplit(h).hostname or "") not in self.config.hosts]
            if external:
                from backend.app.browser_v2.adapters.common import classify_ats

                return JobDetail(**{**detail.__dict__, "apply_mode": "external", "apply_url": external[0],
                                    "ats": classify_ats(external[0])})
        return detail

    async def apply_job(self, page: Any, detail: JobDetail, profile: CandidateFacts | Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        guard_apply(existing_state)
        if detail.challenge:
            return ApplyResult(S.WAITING_FOR_USER, "portal_" + detail.challenge, dry_run,
                               question=HitlQuestion(kind="CAPTCHA", prompt=f"HiringCafe challenge on {detail.listing.url}",
                                                     context={"platform": self.platform}))
        if detail.already_applied:
            return await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                           hitl_answers=hitl_answers)
        if detail.ats in SUPPORTED_ATS and detail.apply_url:
            facts = profile if isinstance(profile, CandidateFacts) else CandidateFacts.from_profile(profile)
            return await self.applier.apply(page, detail, facts, platform=self.platform, dry_run=dry_run,
                                            hitl_answers=hitl_answers)
        host = urlsplit(detail.apply_url or "").hostname or "unknown"
        return ApplyResult(S.FILTERED_OUT, f"external_unsupported_ats:{host}", dry_run)
