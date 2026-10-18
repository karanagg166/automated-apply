"""Tests for direct job source API adapters."""

import pytest
import httpx
from backend.app.services.job_sources.direct_api import (
    GreenhouseAdapter,
    RemotiveAdapter,
    ArbeitnowAdapter,
    HackerNewsHiringAdapter,
)


@pytest.mark.asyncio
async def test_greenhouse_adapter_parsing():
    # Mock Greenhouse API response
    mock_payload = {
        "jobs": [
            {
                "id": 12345,
                "title": "Senior Backend Engineer",
                "absolute_url": "https://job-boards.greenhouse.io/testcompany/jobs/12345",
                "location": {"name": "Remote, US"},
                "content": "<p>We are seeking a Senior Backend Engineer...</p>",
                "updated_at": "2026-10-15T10:00:00Z",
            }
        ]
    }

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=mock_payload)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GreenhouseAdapter(board_token="testcompany", http_client=client)
        jobs = await adapter.fetch_jobs(limit=5)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.source_name == "greenhouse"
        assert job.source_job_id == "12345"
        assert job.title == "Senior Backend Engineer"
        assert job.company_name == "Testcompany"
        assert job.is_remote is True
        assert job.is_confirmed_current is True
        assert "GreenhouseAdapter" in job.data_provenance["adapter"]


@pytest.mark.asyncio
async def test_remotive_adapter_parsing():
    mock_payload = {
        "jobs": [
            {
                "id": 9988,
                "url": "https://remotive.com/job/9988",
                "title": "Python Developer",
                "company_name": "Acme Global",
                "candidate_required_location": "Worldwide",
                "job_type": "full_time",
                "salary": "$120k - $150k",
                "tags": ["python", "fastapi", "docker"],
                "description": "Building next-gen APIs.",
                "publication_date": "2026-10-14T08:00:00Z",
            }
        ]
    }

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=mock_payload)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = RemotiveAdapter(http_client=client)
        jobs = await adapter.fetch_jobs(limit=5)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.source_name == "remotive"
        assert job.title == "Python Developer"
        assert job.company_name == "Acme Global"
        assert job.is_remote is True
        assert job.salary_raw == "$120k - $150k"
        assert "python" in job.skills_required


@pytest.mark.asyncio
async def test_arbeitnow_adapter_parsing():
    mock_payload = {
        "data": [
            {
                "slug": "lead-backend-dev-123",
                "url": "https://www.arbeitnow.com/jobs/lead-backend-dev-123",
                "title": "Lead Backend Developer",
                "company_name": "Berlin Tech Corp",
                "location": "Berlin, Germany",
                "remote": True,
                "job_types": ["full_time"],
                "tags": ["Go", "PostgreSQL"],
                "description": "Lead the team.",
                "created_at": 1729000000,
            }
        ]
    }

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=mock_payload)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = ArbeitnowAdapter(http_client=client)
        jobs = await adapter.fetch_jobs(limit=5)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.source_name == "arbeitnow"
        assert job.title == "Lead Backend Developer"
        assert job.company_name == "Berlin Tech Corp"
        assert job.is_remote is True


@pytest.mark.asyncio
async def test_hacker_news_hiring_adapter_parsing():
    mock_stories = {
        "hits": [
            {"objectID": "40001", "title": "Ask HN: Who is hiring? (October 2026)"}
        ]
    }
    mock_comments = {
        "hits": [
            {
                "objectID": "40002",
                "comment_text": "TechCorp | Senior Python Engineer | Remote (US) | Full-time | $150k-$180k<p>We are hiring engineers.</p>",
            }
        ]
    }

    def handler(req: httpx.Request):
        if "author_whoishiring" in str(req.url):
            return httpx.Response(200, json=mock_stories)
        return httpx.Response(200, json=mock_comments)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = HackerNewsHiringAdapter(http_client=client)
        jobs = await adapter.fetch_jobs(limit=5)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.source_name == "hacker_news"
        assert "TechCorp" in job.company_name
        assert "Senior Python Engineer" in job.title
        assert job.is_remote is True
        assert "$150k" in (job.salary_raw or "")
