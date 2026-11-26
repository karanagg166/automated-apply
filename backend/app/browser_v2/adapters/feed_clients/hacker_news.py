"""Hacker News "Who is hiring?" top-level comments via hn.algolia.com (fixed host)."""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feed_clients.base import (
    FeedSource,
    FeedSourceError,
    check_page,
)
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import (
    employment,
    parse_date,
    remote_policy,
    salary_fields,
)
from backend.app.browser_v2.adapters.feed_clients.validation import posting

STORIES_URL = "https://hn.algolia.com/api/v1/search_by_date"
COMMENTS_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsClient(FeedSource):
    source_name = "hacker_news"

    def __init__(self, http_client: httpx.AsyncClient, **kwargs: Any) -> None:
        super().__init__(http_client, **kwargs)
        # objectID -> the comment's original HTML (the posting keeps tag-stripped text; hrefs live here).
        self.comment_html: dict[str, str] = {}

    async def request(self, url: str, params: Any = None) -> Any:
        data = await super().request(url, params)
        for hit in (data or {}).get("hits", []) if isinstance(data, dict) else []:
            if isinstance(hit, dict) and hit.get("comment_text"):
                self.comment_html[str(hit.get("objectID"))] = str(hit["comment_text"])
        return data

    def parse(self, item: Any, story_id: str, story: Any) -> RawPosting:
        if item.get("parent_id") is not None and str(item["parent_id"]) != story_id:
            raise ValueError("Not a top-level hiring post")
        text = html.unescape(re.sub(r"<[^>]+>", "\n", item["comment_text"]))
        parts = [p.strip() for p in text.split("\n")[0].split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1] or not str(item["objectID"]).isdigit():
            raise ValueError("Missing company/role evidence")
        match = re.search(r"[$€£][\d,kK.]+(?:\s*[-–]\s*[$€£]?[\d,kK.]+)?", text)
        raw = match[0] if match else None
        return posting(
            source_name=self.source_name,
            source_job_id=str(item["objectID"]),
            original_url=f"https://news.ycombinator.com/item?id={item['objectID']}",
            company_name=parts[0],
            title=parts[1],
            description=text,
            location=parts[2] if len(parts) > 2 else None,
            remote_type=remote_policy(" | ".join(parts[2:])),
            employment_type=employment(" | ".join(parts[2:])),
            salary_raw=raw,
            **salary_fields(raw),
            date_posted=parse_date(item.get("created_at")),
            data_provenance={"adapter": "HackerNewsHiringAdapter", "story_id": story_id,
                             "story_title": story["title"]},
        )

    async def fetch_jobs(self, limit: int = 20, page: int = 1) -> list[RawPosting]:
        check_page(limit, page)
        stories = await self.request(STORIES_URL, {"tags": "story,author_whoishiring", "hitsPerPage": 10})
        story = next((s for s in stories["hits"] if re.search(r"who is hiring\?", s.get("title", ""), re.IGNORECASE)), None)
        if story is None:
            return []
        story_id = str(story["objectID"])
        if not story_id.isdigit():
            raise FeedSourceError("Invalid HN story identifier")
        data = await self.request(COMMENTS_URL, {
            "tags": f"comment,story_{story_id}",
            "hitsPerPage": limit,
            "page": page - 1,
            "numericFilters": f"parent_id={story_id}",
        })
        self.next_cursor = str(page + 1) if data.get("nbPages", 1) > page else None
        return self.parse_records(data["hits"], lambda item: self.parse(item, story_id, story), limit)
