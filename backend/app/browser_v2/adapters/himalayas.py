"""Himalayas adapter: official public jobs API discovery + external ATS handoff.

`https://himalayas.app/jobs/api/search?q=` (falls back to `/jobs/api`) is read with a
30-minute cache. Each job's `applicationLink` is classified: Greenhouse/Lever links are
filled by the shared hosted-form filler; other employer sites are classified
`external_unsupported_ats:<host>` (FILTERED_OUT), never guessed at.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.common import html_to_text
from backend.app.browser_v2.adapters.feeds import FeedAdapter, FeedJob

SEARCH_URL = "https://himalayas.app/jobs/api/search"
LIST_URL = "https://himalayas.app/jobs/api"
MAX_BYTES = 8 * 1024 * 1024


def job_id(guid: str | None, title: str | None, company: str | None) -> str:
    path = urlsplit(guid or "").path.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    if re.fullmatch(r"[A-Za-z0-9_-]{3,150}", slug):
        company_slug = path.rsplit("/", 3)[-3] if path.count("/") >= 3 else ""
        return f"{company_slug}:{slug}"[:200] if company_slug else slug
    digest = hashlib.sha256(f"{guid}|{title}|{company}".encode()).hexdigest()[:24]
    return "h-" + digest


def salary(item: dict[str, Any]) -> str | None:
    low, high, currency = item.get("minSalary"), item.get("maxSalary"), item.get("currency") or ""
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and high:
        return f"{currency} {low:,.0f} - {high:,.0f} per year".strip()
    return None


def parse_jobs(payload: Any) -> list[FeedJob]:
    items = payload.get("jobs") if isinstance(payload, dict) else None
    jobs = []
    for item in items if isinstance(items, list) else []:
        title = item.get("title") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not isinstance(title, str):
            continue
        guid = item.get("guid") if isinstance(item.get("guid"), str) else None
        link = item.get("applicationLink") if isinstance(item.get("applicationLink"), str) else None
        posted = item.get("pubDate")
        posted_at = datetime.fromtimestamp(posted, tz=UTC) if isinstance(posted, (int, float)) \
            and not isinstance(posted, bool) and posted > 0 else None
        raw_locations = item.get("locationRestrictions")
        locations: list[Any] = raw_locations if isinstance(raw_locations, list) else []
        jobs.append(FeedJob(
            external_job_id=job_id(guid, item.get("title"), item.get("companyName")),
            url=guid if guid and guid.startswith("https://") else (link or "https://himalayas.app/jobs"),
            title=title.strip(), company=(item.get("companyName") or "").strip() or None,
            apply_url=link if link and link.startswith("https://") else None,
            description=html_to_text(item.get("description") or item.get("excerpt")), posted_at=posted_at,
            location=", ".join(str(x) for x in locations[:5]) or None, salary_text=salary(item), work_mode="remote"))
    return jobs


class HimalayasAdapter(FeedAdapter):
    platform = "himalayas"

    async def _get(self, url: str, params: dict[str, Any]) -> Any:
        client = self.client()
        try:
            response = await client.get(url, params=params)
            if response.status_code != 200 or len(response.content) > MAX_BYTES:
                raise RuntimeError(f"himalayas_http_{response.status_code}")
            return response.json()
        finally:
            if self.http_client is None:
                await client.aclose()

    async def fetch(self, query: str, limit: int) -> list[FeedJob]:
        query = " ".join(query.split())[:100]

        async def load() -> list[FeedJob]:
            if query:
                try:
                    return parse_jobs(await self._get(SEARCH_URL, {"q": query, "sort": "recent"}))
                except Exception:  # noqa: BLE001, S110 - search endpoint down: plain recent list
                    pass
            return parse_jobs(await self._get(LIST_URL, {"limit": 100, "offset": 0}))

        return list(await self.get_cached(f"himalayas:{query.lower()}", load))[:max(limit, 1)]
