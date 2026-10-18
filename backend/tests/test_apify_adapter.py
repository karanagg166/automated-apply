"""Tests for Apify job adapter, portal normalizers, and safety restrictions."""

import pytest
import httpx
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter, ACTOR_CATALOG


def test_strict_linkedin_restriction():
    adapter = ApifyJobAdapter(api_token="test_token")
    with pytest.raises(PermissionError) as exc_info:
        # Should reject synchronous or async attempt immediately
        import asyncio
        asyncio.run(adapter.fetch_jobs(portal="linkedin"))
    assert "STRICT RESTRICTION: LinkedIn" in str(exc_info.value)


def test_naukri_normalization():
    adapter = ApifyJobAdapter()
    sample_item = {
        "id": "nk_9981",
        "title": "Staff Backend Engineer - Python/Go",
        "companyName": "Swiggy",
        "location": "Bengaluru, India",
        "salary": "35-50 Lacs P.A.",
        "skills": "Python, Go, FastAPI, Kubernetes",
        "url": "https://www.naukri.com/job-listings-staff-backend-swiggy-9981",
        "isRemote": False,
        "postedDate": "2026-10-14T05:00:00Z",
    }
    normalized = adapter.normalize_portal_record("naukri", sample_item)
    assert normalized.source_name == "apify_naukri"
    assert normalized.company_name == "Swiggy"
    assert normalized.title == "Staff Backend Engineer - Python/Go"
    assert normalized.location == "Bengaluru, India"
    assert normalized.salary_raw == "35-50 Lacs P.A."
    assert "FastAPI" in normalized.skills_required
    assert normalized.is_confirmed_current is False


def test_wellfound_normalization():
    adapter = ApifyJobAdapter()
    sample_item = {
        "slug": "wf_1122",
        "role": "Founding Backend Engineer",
        "company": {"name": "Nova AI"},
        "location": "Remote",
        "compensation": "$130k – $160k • 0.5% – 1.0%",
        "skills": ["Python", "FastMCP", "PostgreSQL"],
        "jobUrl": "https://wellfound.com/jobs/1122",
        "isRemote": True,
    }
    normalized = adapter.normalize_portal_record("wellfound", sample_item)
    assert normalized.source_name == "apify_wellfound"
    assert normalized.company_name == "Nova AI"
    assert normalized.is_remote is True
    assert "$130k" in (normalized.salary_raw or "")


def test_work_at_a_startup_normalization():
    adapter = ApifyJobAdapter()
    sample_item = {
        "id": "yc_5544",
        "title": "Software Engineer (YC W25)",
        "companyName": "Relay Health",
        "location": "San Francisco, CA",
        "salary": "$140,000 - $170,000",
        "skills": ["Python", "AsyncIO"],
        "url": "https://www.workatastartup.com/jobs/5544",
        "isRemote": False,
    }
    normalized = adapter.normalize_portal_record("work_at_a_startup", sample_item)
    assert normalized.source_name == "apify_work_at_a_startup"
    assert normalized.company_name == "Relay Health"
    assert normalized.source_job_id == "yc_5544"


@pytest.mark.asyncio
async def test_budget_safety_limit_exceeded():
    adapter = ApifyJobAdapter(api_token="test_token")
    adapter.monthly_limit_usd = 0.001  # very low limit
    with pytest.raises(ValueError) as exc_info:
        await adapter.fetch_jobs(portal="hirist", limit=10)
    assert "exceeds configured safety limit" in str(exc_info.value)


@pytest.mark.asyncio
async def test_connection_without_token():
    adapter = ApifyJobAdapter(api_token="")
    status = await adapter.test_connection()
    assert status["status"] == "not_attempted"
    assert "token not configured" in status["message"]
