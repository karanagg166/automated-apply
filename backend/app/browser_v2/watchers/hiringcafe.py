"""HiringCafe discovery through its public MCP endpoint (no browser, no login).

`search_jobs` returns markdown; the parser is tolerant of extra fields and ordering but fails
closed (raises `HiringCafeParseError`) when a result block has no title link or Job ID, or when
the document is not a recognisable result page. `get_job_details` is only called for P0
candidates, to find the employer apply link (Greenhouse/Lever links are handed to those rows).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.app.browser_v2.adapters.common import ats_handoff_target
from backend.app.browser_v2.adapters.feeds import FeedJob

HIRINGCAFE_MCP_URL = "https://hiringcafe.com/api/mcp"
MCP_TIMEOUT_SEC = 30.0
SEARCH_LIMIT = 25
HIRINGCAFE_HOSTS = frozenset({"hiringcafe.com", "www.hiringcafe.com", "hiring.cafe", "www.hiring.cafe"})
JOB_ID = re.compile(r"[A-Za-z0-9_-]{4,120}")
_HEAD = re.compile(r"^#{1,4}\s*\[(?P<title>[^\]\n]{1,300})\]\((?P<url>https://[^\s)]+)\)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^\s*[-*]\s*\*\*(?P<key>[^*:\n]{1,40}):?\*\*:?\s*(?P<value>[^\n]*?)\s*$", re.MULTILINE)
_COMPANY = re.compile(r"^\*\*(?P<company>[^*\n]{1,200})\*\*\s*$", re.MULTILINE)
_RESULTS = re.compile(r"hiring\s*cafe job results", re.IGNORECASE)
_EMPTY = re.compile(r"\bno (?:matching )?jobs\b|\b0 (?:of \d+ )?match(?:es)?\b|showing 0\b|no results", re.IGNORECASE)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_URL = re.compile(r"https://[^\s<>\"'()\[\]]+")


class HiringCafeError(RuntimeError):
    """The MCP call failed or returned an error result."""


class HiringCafeParseError(ValueError):
    """The search markdown is not in the expected shape: nothing from it is trusted."""


@dataclass(frozen=True)
class HiringCafeJob:
    job_id: str
    title: str
    url: str  # canonical HiringCafe page (tracking query dropped)
    company: str | None = None
    location: str | None = None
    workplace: str | None = None
    posted_at: datetime | None = None  # day precision (UTC midnight)

    def feed_job(self) -> FeedJob:
        mode = (self.workplace or "").strip().lower() or None
        return FeedJob(external_job_id=self.job_id, url=self.url, title=self.title, company=self.company,
                       apply_url=None, posted_at=self.posted_at, location=self.location,
                       work_mode=mode if mode in {"remote", "hybrid", "onsite"} else None)


def search_arguments(role: str) -> dict[str, Any]:
    return {"search": role, "posted_within_days": 1, "max_years_experience": 1, "limit": SEARCH_LIMIT,
            "seniority_levels": ["No Prior Experience Required", "Entry Level"]}


def canonical(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _posted(value: str | None) -> datetime | None:
    match = _DATE.search(value or "")
    if not match:
        return None
    try:
        return datetime(int(match[1]), int(match[2]), int(match[3]), tzinfo=UTC)
    except ValueError:
        return None


def parse_search(markdown: str | None) -> list[HiringCafeJob]:
    text = markdown or ""
    heads = list(_HEAD.finditer(text))
    if not heads:
        if _RESULTS.search(text) or _EMPTY.search(text):
            return []
        raise HiringCafeParseError("unrecognised_search_output")
    jobs: list[HiringCafeJob] = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        block = text[head.end():end]
        fields = {m["key"].strip().lower(): m["value"].strip() for m in _FIELD.finditer(block)}
        job_id = fields.get("job id", "").strip("` ")
        url = head["url"]
        if not JOB_ID.fullmatch(job_id):
            raise HiringCafeParseError("missing_job_id")
        if (urlsplit(url).hostname or "").lower() not in HIRINGCAFE_HOSTS:
            raise HiringCafeParseError("unexpected_job_host")
        company = _COMPANY.search(block)
        jobs.append(HiringCafeJob(
            job_id=job_id, title=" ".join(head["title"].split()), url=canonical(url),
            company=company["company"].strip() if company else None, location=fields.get("location") or None,
            workplace=fields.get("workplace") or None, posted_at=_posted(fields.get("posted"))))
    return jobs


def employer_apply_link(markdown: str | None) -> str | None:
    """Greenhouse/Lever posting link first, then the first off-HiringCafe link on an "apply" line."""
    links: list[str] = []
    apply_lines: list[str] = []
    for line in (markdown or "").splitlines():
        found = [link.rstrip(".,;:*_") for link in _URL.findall(line)]
        links.extend(found)
        if "apply" in line.lower():
            apply_lines.extend(found)
    for link in links:
        if ats_handoff_target(link) is not None:
            return link
    for link in apply_lines:
        if (urlsplit(link).hostname or "").lower() not in HIRINGCAFE_HOSTS:
            return link
    return None


async def fastmcp_call(tool: str, arguments: dict[str, Any]) -> str:
    """One stateless call to the public HiringCafe MCP endpoint (fastmcp is imported lazily)."""
    from fastmcp import Client

    async with Client(HIRINGCAFE_MCP_URL, timeout=MCP_TIMEOUT_SEC) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    if result.is_error:
        raise HiringCafeError(f"{tool}_failed")
    return "\n".join(str(text) for block in result.content if (text := getattr(block, "text", None)))
