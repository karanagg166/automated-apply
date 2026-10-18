"""Direct API adapters for official, authorized, or public job feeds."""

import re
from datetime import datetime, timezone
from typing import Any
import httpx

from backend.app.core.logging import logger
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.base import JobSourceAdapter


class GreenhouseAdapter(JobSourceAdapter):
    """Adapter for official public Greenhouse Job Board API."""

    source_name = "greenhouse"

    def __init__(self, board_token: str = "gitlab", http_client: httpx.AsyncClient | None = None) -> None:
        self.board_token = board_token
        self._client = http_client

    async def fetch_jobs(
        self,
        board_token: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        token = board_token or self.board_token
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Greenhouse board {token} returned HTTP {resp.status_code}")
                return []
            data = resp.json()
            raw_jobs = data.get("jobs", [])[:limit]

            normalized: list[NormalizedJob] = []
            for item in raw_jobs:
                updated_at_str = item.get("updated_at")
                date_posted = None
                if updated_at_str:
                    try:
                        date_posted = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                job = NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=str(item.get("id")),
                    original_url=item.get("absolute_url") or f"https://job-boards.greenhouse.io/{token}/jobs/{item.get('id')}",
                    company_name=token.capitalize(),
                    company_domain=f"{token}.com",
                    title=item.get("title", "Untitled Role"),
                    description=item.get("content"),
                    location=item.get("location", {}).get("name") if isinstance(item.get("location"), dict) else str(item.get("location") or ""),
                    is_remote="remote" in (str(item.get("location", "")).lower() + item.get("title", "").lower()),
                    remote_type="remote" if "remote" in str(item.get("location", "")).lower() else "unspecified",
                    employment_type="full_time",
                    experience_level=None,
                    salary_raw=None,
                    skills_required=[],
                    application_url=item.get("absolute_url"),
                    date_posted=date_posted,
                    last_observed_date=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    data_provenance={
                        "adapter": "GreenhouseAdapter",
                        "board_token": token,
                        "raw_id": item.get("id"),
                    },
                    is_confirmed_current=True,
                )
                normalized.append(job)
            return normalized
        except Exception as e:
            logger.error(f"Error fetching from Greenhouse ({token}): {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        try:
            jobs = await self.fetch_jobs(limit=3)
            return {
                "status": "passed" if jobs else "failed",
                "source": self.source_name,
                "sample_count": len(jobs),
                "message": f"Successfully retrieved {len(jobs)} live jobs from Greenhouse ({self.board_token})" if jobs else "No jobs returned",
                "details": {
                    "first_sample": jobs[0].model_dump(mode="json") if jobs else None
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Connection test failed: {e}",
                "details": {},
            }


class RemotiveAdapter(JobSourceAdapter):
    """Adapter for official public Remotive Remote Jobs API."""

    source_name = "remotive"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def fetch_jobs(
        self,
        category: str = "software-dev",
        limit: int = 15,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        url = f"https://remotive.com/api/remote-jobs?category={category}&limit={limit}"

        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Remotive returned HTTP {resp.status_code}")
                return []
            data = resp.json()
            raw_jobs = data.get("jobs", [])[:limit]

            normalized: list[NormalizedJob] = []
            for item in raw_jobs:
                pub_date = None
                if item.get("publication_date"):
                    try:
                        pub_date = datetime.fromisoformat(item["publication_date"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                job = NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=str(item.get("id")),
                    original_url=item.get("url", ""),
                    company_name=item.get("company_name", "Unknown Company"),
                    company_domain=None,
                    title=item.get("title", "Untitled Role"),
                    description=item.get("description"),
                    location=item.get("candidate_required_location") or "Worldwide",
                    is_remote=True,
                    remote_type="remote",
                    employment_type=item.get("job_type", "full_time"),
                    salary_raw=item.get("salary") or None,
                    skills_required=item.get("tags", []),
                    application_url=item.get("url"),
                    date_posted=pub_date,
                    last_observed_date=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    data_provenance={
                        "adapter": "RemotiveAdapter",
                        "category": category,
                        "raw_id": item.get("id"),
                    },
                    is_confirmed_current=True,
                )
                normalized.append(job)
            return normalized
        except Exception as e:
            logger.error(f"Error fetching from Remotive: {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        try:
            jobs = await self.fetch_jobs(limit=3)
            return {
                "status": "passed" if jobs else "failed",
                "source": self.source_name,
                "sample_count": len(jobs),
                "message": f"Successfully retrieved {len(jobs)} live remote software jobs from Remotive" if jobs else "No jobs returned",
                "details": {
                    "first_sample": jobs[0].model_dump(mode="json") if jobs else None
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Connection test failed: {e}",
                "details": {},
            }


class ArbeitnowAdapter(JobSourceAdapter):
    """Adapter for official public Arbeitnow Jobs API."""

    source_name = "arbeitnow"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def fetch_jobs(
        self,
        page: int = 1,
        limit: int = 15,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        url = f"https://www.arbeitnow.com/api/job-board-api?page={page}"

        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Arbeitnow returned HTTP {resp.status_code}")
                return []
            data = resp.json()
            raw_jobs = data.get("data", [])[:limit]

            normalized: list[NormalizedJob] = []
            for item in raw_jobs:
                created_dt = None
                if item.get("created_at"):
                    try:
                        created_dt = datetime.fromtimestamp(item["created_at"], tz=timezone.utc)
                    except Exception:
                        pass

                job = NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=str(item.get("slug")),
                    original_url=item.get("url", ""),
                    company_name=item.get("company_name", "Unknown Company"),
                    company_domain=None,
                    title=item.get("title", "Untitled Role"),
                    description=item.get("description"),
                    location=item.get("location"),
                    is_remote=bool(item.get("remote")),
                    remote_type="remote" if item.get("remote") else "hybrid",
                    employment_type=item.get("job_types", ["full_time"])[0] if item.get("job_types") else "full_time",
                    salary_raw=None,
                    skills_required=item.get("tags", []),
                    application_url=item.get("url"),
                    date_posted=created_dt,
                    last_observed_date=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    data_provenance={
                        "adapter": "ArbeitnowAdapter",
                        "slug": item.get("slug"),
                    },
                    is_confirmed_current=True,
                )
                normalized.append(job)
            return normalized
        except Exception as e:
            logger.error(f"Error fetching from Arbeitnow: {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        try:
            jobs = await self.fetch_jobs(limit=3)
            return {
                "status": "passed" if jobs else "failed",
                "source": self.source_name,
                "sample_count": len(jobs),
                "message": f"Successfully retrieved {len(jobs)} live jobs from Arbeitnow" if jobs else "No jobs returned",
                "details": {
                    "first_sample": jobs[0].model_dump(mode="json") if jobs else None
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Connection test failed: {e}",
                "details": {},
            }


class HackerNewsHiringAdapter(JobSourceAdapter):
    """Adapter for Hacker News 'Who is hiring?' monthly threads via official Algolia API."""

    source_name = "hacker_news"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def fetch_jobs(
        self,
        limit: int = 15,
        **kwargs: Any,
    ) -> list[NormalizedJob]:
        client = self._client or httpx.AsyncClient(timeout=15.0)
        close_client = self._client is None

        try:
            # 1. Find latest Who is hiring story
            story_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=1"
            resp = await client.get(story_url)
            if resp.status_code != 200:
                return []
            stories = resp.json().get("hits", [])
            if not stories:
                return []
            latest_story = stories[0]
            story_id = latest_story.get("objectID")
            story_title = latest_story.get("title", "Who is hiring?")

            # 2. Fetch top level job comments
            comments_url = f"https://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&hitsPerPage={limit * 2}"
            comm_resp = await client.get(comments_url)
            if comm_resp.status_code != 200:
                return []
            comments = comm_resp.json().get("hits", [])

            normalized: list[NormalizedJob] = []
            for comment in comments:
                if len(normalized) >= limit:
                    break
                text = comment.get("comment_text", "")
                if not text or len(text) < 50:
                    continue

                # Parse standard HN hiring title line: Company | Role | Location | ...
                clean_html = re.sub(r"<[^>]+>", " ", text).strip()
                first_line = clean_html.split("\n")[0].split(". ")[0]
                parts = [p.strip() for p in first_line.split("|")]

                company_name = parts[0] if len(parts) >= 1 and len(parts[0]) < 80 else "YC / Startup Company"
                title = parts[1] if len(parts) >= 2 and len(parts[1]) < 100 else "Software Engineer"
                location = parts[2] if len(parts) >= 3 else "Remote / Onsite"

                is_remote = "remote" in clean_html.lower()

                # Extract potential salary/compensation mentions ($100k, €80k, etc.)
                salary_match = re.search(r"(\$[\d,]+k?|\€[\d,]+k?|INR\s*[\d,]+|£[\d,]+k?)(?:\s*[-–—to]+\s*(\$[\d,]+k?|\€[\d,]+k?|INR\s*[\d,]+|£[\d,]+k?))?", clean_html, re.I)
                salary_raw = salary_match.group(0) if salary_match else None

                comment_id = comment.get("objectID")
                hn_url = f"https://news.ycombinator.com/item?id={comment_id}"

                job = NormalizedJob(
                    source_name=self.source_name,
                    source_job_id=str(comment_id),
                    original_url=hn_url,
                    company_name=company_name,
                    company_domain=None,
                    title=title,
                    description=clean_html[:1500],
                    location=location,
                    is_remote=is_remote,
                    remote_type="remote" if is_remote else "unspecified",
                    employment_type="full_time",
                    salary_raw=salary_raw,
                    skills_required=[],
                    application_url=hn_url,
                    date_posted=None,
                    last_observed_date=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    data_provenance={
                        "adapter": "HackerNewsHiringAdapter",
                        "story_id": story_id,
                        "story_title": story_title,
                        "comment_id": comment_id,
                    },
                    is_confirmed_current=True,
                )
                normalized.append(job)

            return normalized
        except Exception as e:
            logger.error(f"Error fetching from Hacker News: {e}")
            return []
        finally:
            if close_client:
                await client.aclose()

    async def test_connection(self) -> dict[str, Any]:
        try:
            jobs = await self.fetch_jobs(limit=3)
            return {
                "status": "passed" if jobs else "failed",
                "source": self.source_name,
                "sample_count": len(jobs),
                "message": f"Successfully retrieved {len(jobs)} live jobs from HN Who is hiring" if jobs else "No jobs returned",
                "details": {
                    "first_sample": jobs[0].model_dump(mode="json") if jobs else None
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "source": self.source_name,
                "sample_count": 0,
                "message": f"Connection test failed: {e}",
                "details": {},
            }
