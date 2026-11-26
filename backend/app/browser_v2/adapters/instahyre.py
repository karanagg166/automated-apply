"""Instahyre adapter (persistent Brave profile).

Matched opportunities -> job page -> deterministic one-click "Apply"/"Interested" +
modal screening questions (4-tier resolver / HITL) -> confirmation text or applied badge.
Dry-run stops before the Apply click (it may submit at once).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.adapters.common import (
    InteractivePortalAdapter,
    PortalConfig,
)

ORIGIN = "https://www.instahyre.com"


OPP_SELECTOR = '[ng-repeat*="opp in opportunities"], #employer-profile-opportunity'
OPPS_JS = r"""
({limit}) => {
  if (!window.angular) return [];
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll('#employer-profile-opportunity')) {
    let opp = null;
    try { opp = window.angular.element(el).scope().opp; } catch (e) { continue; }
    if (!opp || !opp.job || seen.has(opp.job.id)) continue;
    seen.add(opp.job.id);
    out.push({id: opp.job.id, url: opp.job.opportunity_url || null, title: opp.job.title || opp.job.candidate_title || null,
              company: (opp.employer && opp.employer.company_name) || opp.job.hiring_company_name || null,
              internship: !!opp.job.is_internship});
    if (out.length >= limit) break;
  }
  return out;
}
"""


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

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        """Live 2026-11-26: the logged-in opportunities page is an Angular ng-repeat whose rows have NO
        job links (clicking one calls openApplyModal). Read the `opp` objects instead - never click."""
        await self._goto(page, self.search_url(query, job_age_days))
        try:
            await page.wait_for_selector(OPP_SELECTOR, timeout=12_000)
        except Exception:  # noqa: BLE001 - logged out / empty / changed: fall back to link cards
            return await super().discover_jobs(page, query=query, limit=limit, job_age_days=job_age_days)
        if (await self._probe(page)).get("challenge"):
            self.last_discovery_blocked = "challenge"
            return []
        rows = await page.evaluate(OPPS_JS, {"limit": max(1, min(limit, 50))})
        listings: list[JobListing] = []
        for row in rows or []:
            url = urljoin(ORIGIN + "/", str(row.get("url") or ""))
            match = re.match(self.config.job_path, urlsplit(url).path)
            job_id = match.group(1) if match else (str(row.get("id")) if str(row.get("id") or "").isdigit() else None)
            if not job_id:
                continue
            if not match:  # stable public job page for this id
                url = f"{ORIGIN}/job-{job_id}/"
            listings.append(JobListing(platform=self.platform, external_job_id=job_id, url=url,
                                       title=row.get("title"), company=(row.get("company") or "")[:120] or None,
                                       posted_text=None, posted_age_days=None))
        if not listings:
            return await super().discover_jobs(page, query=query, limit=limit, job_age_days=job_age_days)
        return listings
