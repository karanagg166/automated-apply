"""Discovery + job inspection mixin of `InteractivePortalAdapter`."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

from backend.app.browser_v2.adapters.base import JobDetail, JobListing
from backend.app.browser_v2.adapters.shared.dom_scripts import (
    CARDS_JS,
    COMPANY_BADGE,
    DETAIL_JS,
    MARK_APPLY_JS,
)
from backend.app.browser_v2.adapters.shared.external_handoff import classify_ats
from backend.app.browser_v2.adapters.shared.portal_base import PortalAdapterBase
from backend.app.browser_v2.forms import extract_form
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    parse_applicants,
    parse_posted_age_days,
)


class PortalDiscoveryMixin(PortalAdapterBase):
    """search_url / discover_jobs / inspect_job and the Apply-control resolution."""

    # --- discovery ----------------------------------------------------------------------
    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        raise NotImplementedError

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        await self._goto(page, self.search_url(query, job_age_days))
        await self._wait_for_results(page)
        if (await self._probe(page)).get("challenge"):
            # Live 2026-11-26 (hiringcafe.com behind Cloudflare): never parse cards off an interstitial;
            # the next session check isolates the portal (AUTH_REQUIRED/challenge).
            self.last_discovery_blocked = "challenge"
            return []
        self.last_discovery_blocked = None
        items = await page.evaluate(CARDS_JS, {"pattern": self.config.job_path, "limit": max(1, min(limit, 50)),
                                               "hosts": list(self.config.hosts)})
        listings = []
        for item in items:
            posted = item.get("posted")
            company = COMPANY_BADGE.sub("", item.get("company") or "").strip() or None
            listings.append(JobListing(
                platform=self.platform, external_job_id=str(item["id"]), url=item["url"],
                title=item.get("title"), company=company, posted_text=posted,
                posted_age_days=parse_posted_age_days(posted), age_is_lower_bound=bool(posted and "+" in posted),
                applicants=parse_applicants(item.get("applicants")) if item.get("applicants") else None))
        return listings

    # --- inspection ---------------------------------------------------------------------
    def _detail_args(self) -> dict[str, Any]:
        return {"applyRe": self.config.apply_text, "appliedRe": self.config.applied_text,
                "externalRe": self.config.external_text, "applySel": self.config.apply_selector,
                "companySel": self.config.company_selector, "hintRe": self.config.unsupported_apply_text}

    async def resolve_apply_control(self, page: Any, polls: int = 12) -> dict[str, Any]:
        """Same counting as inspection; waits (<= ~3 s) for two identical reads (SPA hydration)."""
        args = {"applyRe": self.config.apply_text, "appliedRe": self.config.applied_text,
                "applySel": self.config.apply_selector}
        previous: int | None = None
        state: dict[str, Any] = {}
        for attempt in range(max(1, polls)):
            state = await page.evaluate(MARK_APPLY_JS, args)
            if state.get("applied") or (state.get("count") == 1 and previous == 1):
                return state
            previous = state.get("count")
            if attempt + 1 < polls:
                await page.wait_for_timeout(250)
        return state

    async def _primary_apply(self, page: Any) -> list[Any]:
        if not self.config.apply_selector:
            return []
        locator = page.locator(self.config.apply_selector)
        found = []
        for index in range(min(await locator.count(), 5)):
            item = locator.nth(index)
            try:
                if await item.is_visible() and await item.is_enabled():
                    found.append(item)
            except Exception:  # noqa: BLE001, S112
                continue
        return found

    async def _wait_for_job_page(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Logged-in SPAs render the job title after DOMContentLoaded (live canary 2026-11-27):
        wait for a non-empty h1, an apply/applied control, or a login/challenge page."""
        try:
            await page.wait_for_function(
                "([applyRe]) => { const h = document.querySelector('h1'); if (h && h.innerText.trim()) return true;"
                " const re = new RegExp(applyRe, 'i'); return [...document.querySelectorAll('button, a')]"
                ".some(b => re.test((b.innerText || '').trim())) || /login|signin|sign_in/i.test(location.pathname); }",
                arg=[self.config.apply_text], timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - timeout: parse whatever rendered; filters fail closed
            return

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        await self._goto(page, listing.url)
        await self._wait_for_job_page(page)
        auth = self.classify_auth(await self._probe(page))
        data = await page.evaluate(DETAIL_JS, self._detail_args())
        applicants = parse_applicants(data.get("applicants")) if data.get("applicants") else (
            listing.applicants or UNKNOWN_APPLICANTS)
        # Card age first (calibrated per portal), then the job page: visible "posted ..." text,
        # then structured data (JSON-LD datePosted / <time datetime>) - Phase 8 unknown-age layer 1.
        age = listing.posted_age_days
        if data.get("posted"):
            age = parse_posted_age_days(data.get("posted"))
        if age is None and data.get("datePosted"):
            age = parse_posted_age_days(str(data["datePosted"])[:10])
        external = data.get("externalLinks") or []
        if data.get("applied"):
            mode = "applied"
        elif data.get("applyButtons") == 1:
            mode = "direct"
        elif external:
            mode = "external"
        elif data.get("applyButtons"):
            mode = "ambiguous"
        elif data.get("unsupportedApply"):
            mode = "unsupported_ui"
        else:
            mode = "closed" if data.get("closed") else "none"
        if mode == "none" and data.get("loginToApply") and auth == "unknown":
            auth = "login"  # logged-out job page that hides Apply behind "log in to apply"
        apply_url = urljoin(listing.url, external[0]) if mode == "external" and external else None
        merged = replace(listing, title=data.get("title") or listing.title,
                         # the calibrated card value wins; detail-page text is only a fallback
                         company=listing.company or data.get("company"),
                         posted_text=data.get("posted") or listing.posted_text, posted_age_days=age,
                         applicants=applicants)
        return JobDetail(
            listing=merged, applicants=applicants, posted_age_days=age, already_applied=bool(data.get("applied")),
            apply_mode=mode, challenge=auth if auth in {"challenge", "otp", "login"} else None,
            portal_limit=await self.detect_portal_limit(page), description=data.get("description"),
            salary_text=data.get("salary"), location=data.get("location"), work_mode=data.get("workMode"),
            apply_url=apply_url, ats=classify_ats(apply_url))

    async def extract_form(self, page: Any) -> dict[str, Any]:
        return await extract_form(page)

    async def detect_portal_limit(self, page: Any) -> str | None:
        body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        match = re.search(self.config.limit_text, body or "", re.IGNORECASE)
        return match.group(0) if match else None
