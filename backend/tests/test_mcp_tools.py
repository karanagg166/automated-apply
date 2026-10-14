"""Tests for FastMCP foundational tools."""

import pytest
from backend.app.mcp_server import (
    lookup_or_create_company,
    get_cached_company_contacts,
    generate_company_email_candidates,
    save_discovered_job,
    check_api_credits_status,
)
from backend.app.repositories.contact import ContactRepository
from backend.app.repositories.company import CompanyRepository
import uuid


@pytest.mark.asyncio
async def test_mcp_lookup_or_create_company():
    result = await lookup_or_create_company(
        name="Vercel",
        domain="vercel.com",
    )
    assert result["name"] == "Vercel"
    assert result["domain"] == "vercel.com"
    assert result["was_created"] is True

    # Re-query
    result_existing = await lookup_or_create_company(
        name="Vercel Inc",
        domain="vercel.com",
    )
    assert result_existing["id"] == result["id"]
    assert result_existing["was_created"] is False


@pytest.mark.asyncio
async def test_mcp_generate_company_email_candidates():
    candidates = generate_company_email_candidates(
        first_name="Guillermo",
        last_name="Rauch",
        domain="vercel.com",
    )
    assert len(candidates) > 0
    candidate_emails = [c["email"] for c in candidates]
    assert "guillermo.rauch@vercel.com" in candidate_emails

    for c in candidates:
        assert c["status"] == "candidate"
        assert "NOT a verified mailbox" in c["disclaimer"]


@pytest.mark.asyncio
async def test_mcp_save_discovered_job():
    job_result = await save_discovered_job(
        title="Full Stack Engineer",
        job_url="https://vercel.com/careers/123",
        source_platform="greenhouse",
        company_name="Vercel",
        company_domain="vercel.com",
        location="Remote, Global",
        is_remote=True,
        match_score=92.5,
        match_explanation="Matches Next.js and TypeScript experience",
    )
    assert job_result["title"] == "Full Stack Engineer"
    assert job_result["was_created"] is True

    # Duplicate job URL
    dup_result = await save_discovered_job(
        title="Full Stack Engineer",
        job_url="https://vercel.com/careers/123",
        source_platform="linkedin",
        company_name="Vercel",
    )
    assert dup_result["id"] == job_result["id"]
    assert dup_result["was_created"] is False


@pytest.mark.asyncio
async def test_mcp_check_api_credits_status():
    status = await check_api_credits_status()
    assert "timestamp" in status
    assert "providers" in status
    assert "total_credits_remaining" in status
