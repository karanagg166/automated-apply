"""Naukri search URLs, job ids, discovery and job inspection."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlsplit

from backend.app.browser_v2.adapters.base import JobDetail, JobListing
from backend.app.browser_v2.adapters.naukri.auth import NaukriAuthMixin, classify_auth
from backend.app.browser_v2.adapters.naukri.constants import (
    JOB_PATH,
    ORIGIN,
    PORTAL_LIMIT,
)
from backend.app.browser_v2.adapters.naukri.dom_scripts import DETAIL_JS, LISTING_JS
from backend.app.browser_v2.forms import extract_form
from backend.app.browser_v2.rules import parse_applicants, parse_posted_age_days


def search_url(query: str, *, job_age_days: int | None = None) -> str:
    if query.startswith(ORIGIN + "/"):
        return query
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "jobs"
    url = f"{ORIGIN}/{slug}-jobs?k={quote_plus(query)}"
    if job_age_days:
        allowed = [d for d in (1, 3, 7, 15, 30) if d >= job_age_days]
        url += f"&jobAge={allowed[0] if allowed else 30}"
    return url


def external_job_id(url: str) -> str | None:
    match = JOB_PATH.match(urlsplit(url).path)
    return match.group(1) if match else None


class NaukriDiscoveryMixin(NaukriAuthMixin):
    """discover_jobs / inspect_job / extract_form / detect_portal_limit."""

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        await self._goto(page, search_url(query, job_age_days=job_age_days))
        try:  # live 2026-11-26: logged-in SRP renders its job tuples after DOMContentLoaded
            await page.wait_for_selector('a[href*="/job-listings-"]', timeout=12_000)
        except Exception:  # noqa: BLE001, S110 - parse whatever rendered (maybe a "no jobs" page)
            pass
        data = await page.evaluate(LISTING_JS, {"limit": max(1, min(limit, 50))})
        listings = []
        for item in data["jobs"]:
            posted = item.get("posted")
            listings.append(JobListing(
                platform=self.platform, external_job_id=item["id"], url=item["url"],
                title=item.get("title"), company=item.get("company"), posted_text=posted,
                posted_age_days=parse_posted_age_days(posted),
                age_is_lower_bound=bool(posted and "+" in posted), experience_text=item.get("experience")))
        return listings

    async def _wait_for_job_header(self, page: Any, timeout_ms: int = 15_000) -> None:
        """Live canary 2026-11-27: on a cold load the React JD header renders well after
        DOMContentLoaded; reading it early returned no title/age/JD and the job was filtered as
        needs_review. Wait for the header h1 (or a login/expired page), then read."""
        try:
            await page.wait_for_function(
                "() => { const h = document.querySelector('#job_header h1, [class*=\"jd-header\"] h1, "
                "[class*=\"jdHeader\"] h1'); return (h && h.innerText.trim().length > 0) || "
                "/nlogin|login/i.test(location.pathname) || "
                "/no longer (?:available|active)|job (?:has )?expired/i.test(document.body ? document.body.innerText : ''); }",
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - parse whatever rendered; the filters fail closed
            return

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        await self._goto(page, listing.url)
        await self._wait_for_job_header(page)
        probe = await self._probe(page)
        auth = classify_auth(probe)
        data = await page.evaluate(DETAIL_JS)
        applicant_labels = data.get("applicants") or []
        applicants = parse_applicants(applicant_labels[0] if len(applicant_labels) == 1 else None)
        age = (parse_posted_age_days(data["datePosted"]) if data.get("datePosted")
               else parse_posted_age_days(data.get("posted")) if data.get("posted")
               else listing.posted_age_days)
        if data.get("applied"):
            mode = "applied"
        elif data.get("external"):
            mode = "external"
        elif data.get("applyButtons") == 1:
            mode = "direct"
        else:
            mode = "ambiguous" if data.get("applyButtons") else ("closed" if data.get("closed") else "none")
        merged = JobListing(
            platform=self.platform, external_job_id=listing.external_job_id, url=listing.url,
            title=data.get("title") or listing.title, company=data.get("company") or listing.company,
            posted_text=data.get("posted") or listing.posted_text, posted_age_days=age,
            age_is_lower_bound=listing.age_is_lower_bound and not data.get("datePosted"),
            applicants=applicants, experience_text=data.get("experience") or listing.experience_text)
        return JobDetail(
            listing=merged, applicants=applicants, posted_age_days=age,
            already_applied=bool(data.get("applied")), apply_mode=mode,
            challenge=auth if auth in {"challenge", "otp", "login"} else None,
            portal_limit=await self.detect_portal_limit(page),
            description=data.get("description"), salary_text=data.get("salary"),
            location=data.get("location"), work_mode=data.get("workMode"),
            apply_url=data.get("externalUrl") if mode == "external" else None)

    async def extract_form(self, page: Any) -> dict[str, Any]:
        return await extract_form(page)

    async def detect_portal_limit(self, page: Any) -> str | None:
        body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        match = PORTAL_LIMIT.search(body or "")
        return match.group(0) if match else None
