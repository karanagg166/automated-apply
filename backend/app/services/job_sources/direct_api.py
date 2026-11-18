"""Read-only fixed-host public feeds. No URL supplied by a user is fetched."""

import asyncio
import html
import json
import re
from time import perf_counter

import httpx

from backend.app.core.config import get_settings
from backend.app.schemas.discovery import (
    DiscoveryError,
    DiscoveryQuery,
)
from backend.app.schemas.discovery import (
    DiscoveryStatus as Status,
)
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.normalization import (
    employment,
    parse_date,
    remote_policy,
    salary_fields,
)


class DirectAdapter(JobSourceAdapter):
    def __init__(self, http_client=None):
        self._client = http_client
        self.record_errors = []
        self.next_cursor = None
        self.last_http_status = None
        self.retry_after_seconds = None
        self.metrics = {}

    # Cap decoded bytes as well as the deadline; a public feed is untrusted input.
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024
    JSON_TYPES = (dict,)

    async def retry_pause(self):
        started = perf_counter()
        try:
            await asyncio.sleep(0.1)
        finally:
            self.metrics["retry_wait_seconds"] = (
                self.metrics.get("retry_wait_seconds", 0) + perf_counter() - started
            )

    async def request(self, client, url, params=None):
        started = perf_counter()
        try:
            return await self._request(client, url, params)
        finally:
            self.metrics["request_seconds"] = (
                self.metrics.get("request_seconds", 0) + perf_counter() - started
            )

    async def _request(self, client, url, params=None):
        attempts = 1 if self.source_name == "remotive" else 2
        for attempt in range(attempts):
            try:
                self.metrics["http_attempts"] = self.metrics.get("http_attempts", 0) + 1
                async with client.stream(
                    "GET", url, params=params, timeout=15, follow_redirects=False
                ) as response:
                    code = response.status_code
                    self.last_http_status = code
                    if code == 429:
                        try:
                            self.retry_after_seconds = min(
                                604800,
                                max(0, int(response.headers.get("Retry-After", "0"))),
                            )
                        except ValueError:
                            self.retry_after_seconds = None
                        raise DiscoveryError(
                            Status.RATE_LIMITED, "Provider rate limited; retry later"
                        )
                    if code in (401, 403):
                        raise DiscoveryError(
                            Status.AUTH_REQUIRED, "Provider authorization required"
                        )
                    if code >= 500 and attempt + 1 < attempts:
                        await self.retry_pause()
                        continue
                    if code != 200:
                        raise DiscoveryError(
                            Status.UNAVAILABLE, f"Provider returned HTTP {code}"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.MAX_RESPONSE_BYTES:
                            raise DiscoveryError(
                                Status.UPSTREAM_ERROR,
                                "Provider response exceeds size limit",
                            )
                        body.extend(chunk)
                    self.metrics["decoded_bytes"] = self.metrics.get(
                        "decoded_bytes", 0
                    ) + len(body)
                    try:
                        started = perf_counter()
                        try:
                            data = json.loads(body)
                        finally:
                            self.metrics["json_seconds"] = (
                                self.metrics.get("json_seconds", 0)
                                + perf_counter()
                                - started
                            )
                        if not isinstance(data, self.JSON_TYPES):
                            raise ValueError("Invalid top-level schema")
                        return data
                    except (ValueError, UnicodeError):
                        raise DiscoveryError(
                            Status.UPSTREAM_ERROR, "Provider returned invalid JSON"
                        ) from None
            except httpx.TransportError:
                if attempt + 1 < attempts:
                    await self.retry_pause()
                    continue
                raise DiscoveryError(
                    Status.UPSTREAM_ERROR, "Provider transport failed"
                ) from None

    def parse_records(self, records, parser, limit):
        if not isinstance(records, list):
            raise DiscoveryError(
                Status.UPSTREAM_ERROR, "Provider returned an invalid record collection"
            )
        result = []
        self.record_errors = []
        started = perf_counter()
        try:
            for index, record in enumerate(records[:limit]):
                try:
                    result.append(parser(record))
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    self.record_errors.append(
                        f"Record {index}: invalid or missing listing evidence"
                    )
        finally:
            self.metrics["normalization_seconds"] = (
                self.metrics.get("normalization_seconds", 0) + perf_counter() - started
            )
        return result

    async def discover(self, query: DiscoveryQuery, **kwargs):
        self.record_errors = []
        self.next_cursor = None
        self.last_http_status = None
        self.retry_after_seconds = None
        self.metrics = {}
        started = perf_counter()
        result = await super().discover(query, **kwargs)
        result.usage = {
            **result.usage,
            "public_feed": {
                **self.metrics,
                "adapter_seconds": round(perf_counter() - started, 6),
            },
        }
        if self.record_errors and result.status in (Status.SUCCESS, Status.NO_RESULTS):
            result.errors = self.record_errors
            result.rejected_count = len(self.record_errors)
            result.status = Status.PARTIAL if result.jobs else Status.UPSTREAM_ERROR
        result.next_cursor = self.next_cursor
        return result

    async def test_connection(self):
        result = await self.discover(DiscoveryQuery(limit=1))
        return {
            "source": self.source_name,
            "status": "passed"
            if result.status in (Status.SUCCESS, Status.NO_RESULTS)
            else "not_attempted"
            if self.validate_configuration()
            else "failed",
            "sample_count": len(result.jobs),
            "message": result.status,
            "details": {"errors": result.errors},
        }

    def client(self):
        return self._client or httpx.AsyncClient(timeout=15, follow_redirects=False)


class GreenhouseAdapter(DirectAdapter):
    source_name = "greenhouse"
    query_parameters = ["page", "limit", "configured_boards"]

    def __init__(self, board_token=None, http_client=None, company_name=None):
        super().__init__(http_client)
        self.boards = get_settings().GREENHOUSE_BOARDS
        self.board_token = board_token
        self.company_name = company_name

    def validate_configuration(self):
        return (
            []
            if self.board_token or self.boards
            else ["Configure GREENHOUSE_BOARDS with board-token/company-name pairs"]
        )

    async def fetch_jobs(self, board_token=None, limit=20, page=1, **kwargs):
        DiscoveryQuery(limit=limit, page=page)
        boards = (
            {board_token or self.board_token: self.company_name}
            if board_token or self.board_token
            else self.boards
        )
        if not boards:
            raise DiscoveryError(
                Status.CONFIGURATION_REQUIRED, "Greenhouse boards are not configured"
            )
        jobs, errors = [], []
        start = (page - 1) * limit
        remaining = limit
        self.next_cursor = None
        client = self.client()
        try:
            board_items = list(boards.items())[:10]
            for board_index, (token, company) in enumerate(board_items):
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", token):
                    raise DiscoveryError(
                        Status.CONFIGURATION_REQUIRED, "Invalid board token"
                    )
                data = await self.request(
                    client,
                    f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                    {"content": "true"},
                )
                records = data["jobs"]
                if not isinstance(records, list):
                    raise DiscoveryError(
                        Status.UPSTREAM_ERROR, "Invalid board jobs collection"
                    )
                if start >= len(records):
                    start -= len(records)
                    continue

                def parse(item):
                    location = (item.get("location") or {}).get("name")
                    source_id = item.get("id")
                    if (
                        isinstance(source_id, bool)
                        or not isinstance(source_id, (str, int))
                        or not str(source_id).strip()
                    ):
                        raise ValueError("Greenhouse record requires a non-empty scalar id")
                    return NormalizedJob(
                        source_name=self.source_name,
                        source_job_id=str(source_id),
                        original_url=item["absolute_url"],
                        application_url=item["absolute_url"],
                        company_name=item.get("company_name") or company,
                        title=item["title"],
                        description=item.get("content"),
                        location=location,
                        remote_type=remote_policy(location),
                        date_posted=parse_date(item.get("first_published")),
                        source_verification_status="source_reported",
                        is_confirmed_current=True,
                        data_provenance={
                            "adapter": type(self).__name__,
                            "board_token": token,
                            "updated_at": item.get("updated_at"),
                            "source_fields": {
                                k: v for k, v in item.items() if k != "content"
                            },
                        },
                    )

                selected = records[start : start + remaining]
                jobs.extend(self.parse_records(selected, parse, remaining))
                errors.extend(self.record_errors)
                remaining -= len(selected)
                if (
                    len(records) > start + len(selected)
                    or board_index < len(board_items) - 1
                ):
                    self.next_cursor = str(page + 1)
                start = 0
                if remaining <= 0:
                    break
            self.record_errors = errors
            return jobs
        finally:
            if self._client is None:
                await client.aclose()


class RemotiveAdapter(DirectAdapter):
    source_name = "remotive"
    query_parameters = ["search_query", "category", "page", "limit"]

    async def fetch_jobs(
        self, category="software-dev", limit=20, page=1, search_query="", **kwargs
    ):
        DiscoveryQuery(limit=limit, page=page)
        if page * limit > 1000:
            raise DiscoveryError(
                Status.UNSUPPORTED,
                "Remotive local pagination is capped at 1000 feed records",
            )
        client = self.client()
        try:
            data = await self.request(
                client,
                "https://remotive.com/api/remote-jobs",
                {
                    "category": category,
                    "limit": min(page * limit, 1000),
                    "search": search_query,
                },
            )

            def parse(item):
                raw = item.get("salary") or None
                source_id = item.get("id")
                if (
                    isinstance(source_id, bool)
                    or not isinstance(source_id, (str, int))
                    or not str(source_id).strip()
                ):
                    raise ValueError("Remotive record requires a non-empty scalar id")
                return NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=str(source_id),
                    original_url=item["url"],
                    company_name=item.get("company_name"),
                    title=item["title"],
                    description=item.get("description"),
                    location=item.get("candidate_required_location"),
                    remote_type="remote",
                    employment_type=employment(item.get("job_type")),
                    salary_raw=raw,
                    **salary_fields(raw),
                    skills_required=item.get("tags") or [],
                    date_posted=parse_date(item.get("publication_date")),
                    source_verification_status="source_reported",
                    data_provenance={
                        "adapter": type(self).__name__,
                        "attribution": "Remotive",
                        "feed_delay_hours": 24,
                    },
                )

            return self.parse_records(
                data["jobs"][(page - 1) * limit : page * limit], parse, limit
            )
        finally:
            if self._client is None:
                await client.aclose()


class ArbeitnowAdapter(DirectAdapter):
    source_name = "arbeitnow"
    query_parameters = ["page", "limit"]

    async def fetch_jobs(self, page=1, limit=20, **kwargs):
        DiscoveryQuery(limit=limit, page=page)
        client = self.client()
        try:
            data = await self.request(
                client, "https://www.arbeitnow.com/api/job-board-api", {"page": page}
            )

            def parse(item):
                remote = "remote" if item.get("remote") is True else "unknown"
                return NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=item["slug"],
                    original_url=item["url"],
                    company_name=item.get("company_name"),
                    title=item["title"],
                    description=item.get("description"),
                    location=item.get("location"),
                    remote_type=remote,
                    employment_type=employment(" ".join(item.get("job_types") or [])),
                    # Feed tags include categories and seniority, not required skills.
                    date_posted=parse_date(item.get("created_at")),
                    source_verification_status="source_reported",
                    data_provenance={
                        "adapter": type(self).__name__,
                        "page": page,
                        "attribution": "Arbeitnow",
                        "attribution_url": "https://www.arbeitnow.com",
                        "source_fields": {
                            k: v for k, v in item.items() if k != "description"
                        },
                    },
                )

            links = data.get("links") or {}
            if not isinstance(links, dict):
                raise DiscoveryError(
                    Status.UPSTREAM_ERROR, "Invalid pagination metadata"
                )
            # Ignore upstream links; only fixed host + integer page is requested.
            self.next_cursor = (
                str(page + 1) if links.get("next") and page < 100 else None
            )
            return self.parse_records(data["data"], parse, limit)
        finally:
            if self._client is None:
                await client.aclose()


class HackerNewsHiringAdapter(DirectAdapter):
    source_name = "hacker_news"
    query_parameters = ["page", "limit"]

    async def fetch_jobs(self, limit=20, page=1, **kwargs):
        DiscoveryQuery(limit=limit, page=page)
        client = self.client()
        try:
            stories = await self.request(
                client,
                "https://hn.algolia.com/api/v1/search_by_date",
                {"tags": "story,author_whoishiring", "hitsPerPage": 10},
            )
            story = next(
                (
                    s
                    for s in stories["hits"]
                    if re.search(r"who is hiring\?", s.get("title", ""), re.I)
                ),
                None,
            )
            if story is None:
                return []
            story_id = str(story["objectID"])
            if not story_id.isdigit():
                raise DiscoveryError(
                    Status.UPSTREAM_ERROR, "Invalid HN story identifier"
                )
            data = await self.request(
                client,
                "https://hn.algolia.com/api/v1/search",
                {
                    "tags": f"comment,story_{story_id}",
                    "hitsPerPage": limit,
                    "page": page - 1,
                    "numericFilters": f"parent_id={story_id}",
                },
            )

            def parse(item):
                if (
                    item.get("parent_id") is not None
                    and str(item["parent_id"]) != story_id
                ):
                    raise ValueError("Not a top-level hiring post")
                text = html.unescape(re.sub(r"<[^>]+>", "\n", item["comment_text"]))
                parts = [p.strip() for p in text.split("\n")[0].split("|")]
                if (
                    len(parts) < 2
                    or not parts[0]
                    or not parts[1]
                    or not str(item["objectID"]).isdigit()
                ):
                    raise ValueError("Missing company/role evidence")
                raw = re.search(r"[$€£][\d,kK.]+(?:\s*[-–]\s*[$€£]?[\d,kK.]+)?", text)
                raw = raw[0] if raw else None
                return NormalizedJob(
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
                    data_provenance={
                        "adapter": type(self).__name__,
                        "story_id": story_id,
                        "story_title": story["title"],
                    },
                )

            self.next_cursor = str(page + 1) if data.get("nbPages", 1) > page else None
            return self.parse_records(data["hits"], parse, limit)
        finally:
            if self._client is None:
                await client.aclose()
