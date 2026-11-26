"""We Work Remotely adapter: official public RSS discovery + external ATS handoff.

Reads https://weworkremotely.com/remote-jobs.rss (plus the programming category feeds,
overridable with WWR_FEEDS) at most once per 30 minutes. The listing page's "Apply"
link is resolved in the worker tab; Greenhouse/Lever links are filled by the shared
hosted-form filler, anything else is `external_unsupported_ats:<host>`. Receipts carry
the required "via We Work Remotely" attribution.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from backend.app.browser_v2.adapters.common import html_to_text
from backend.app.browser_v2.adapters.feeds import FeedAdapter, FeedJob

DEFAULT_FEEDS = ("https://weworkremotely.com/remote-jobs.rss",
                 "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
                 "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss")
MAX_BYTES = 5 * 1024 * 1024
ORIGIN_HOSTS = frozenset({"weworkremotely.com", "www.weworkremotely.com"})
JOB_PATH = re.compile(r"^/remote-jobs/([A-Za-z0-9_-]{3,200})/?$")

APPLY_LINK_JS = r"""
() => {
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const links = [...document.querySelectorAll("a[href]")].filter(visible)
    .filter(a => /apply/i.test((a.innerText || "").trim()) || a.id === "job-cta-alt" || a.id === "job-cta-alt-2");
  return links.map(a => a.href).filter(h => /^https:\/\//.test(h)).slice(0, 3);
}
"""


def feeds() -> tuple[str, ...]:
    raw = os.environ.get("WWR_FEEDS", "")
    custom = tuple(u.strip() for u in raw.split(",") if u.strip().startswith("https://weworkremotely.com/"))
    return custom or DEFAULT_FEEDS


def parse_rss(xml_bytes: bytes) -> list[FeedJob]:
    if len(xml_bytes) > MAX_BYTES or b"<!ENTITY" in xml_bytes[:4096]:
        return []  # untrusted XML: no DTD entities, bounded size
    root = ET.fromstring(xml_bytes)
    jobs = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        match = JOB_PATH.match(urlsplit(link).path)
        if not title or not match or (urlsplit(link).hostname or "") not in ORIGIN_HOSTS:
            continue
        company, _, role = title.partition(":")
        posted = None
        try:
            posted = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            posted = None
        jobs.append(FeedJob(external_job_id=match.group(1), url=link, title=(role or title).strip(),
                            company=company.strip() if role else None, apply_url=None,
                            description=html_to_text(item.findtext("description")), posted_at=posted,
                            location=(item.findtext("region") or "").strip() or None, work_mode="remote"))
    return jobs


class WeWorkRemotelyAdapter(FeedAdapter):
    platform = "we_work_remotely"
    attribution = "Listing via We Work Remotely (weworkremotely.com)"

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        async def load() -> list[FeedJob]:
            client = self.client()
            seen: dict[str, FeedJob] = {}
            try:
                for url in feeds():
                    try:
                        response = await client.get(url)
                    except Exception:  # noqa: BLE001, S112
                        continue
                    if response.status_code == 200:
                        for job in parse_rss(response.content):
                            seen.setdefault(job.external_job_id, job)
            finally:
                if self.http_client is None:
                    await client.aclose()
            return list(seen.values())

        return list(await self.get_cached("wwr:feeds", load))

    async def resolve_apply_url(self, page: Any, job: FeedJob) -> str | None:
        """The RSS has no apply link: read it from the listing page (one navigation)."""
        await page.goto(job.url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.applier.settle_ms)
        for href in await page.evaluate(APPLY_LINK_JS):
            absolute = urljoin(job.url, href)
            if (urlsplit(absolute).hostname or "") not in ORIGIN_HOSTS:
                return absolute
        return None
