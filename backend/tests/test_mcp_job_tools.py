"""Tests for job discovery and application assistance tools registered on FastMCP server."""

import pytest
from backend.app.mcp_server import (
    check_job_source_connection,
    fetch_jobs_from_source,
    ingest_jobs_from_source,
    match_job_against_profile,
    generate_application_draft,
    update_job_application_status,
    save_discovered_job,
)


@pytest.mark.asyncio
async def test_mcp_check_job_source_connection():
    res = await check_job_source_connection("remotive")
    assert res["source"] == "remotive"
    assert res["status"] in ("passed", "failed")


@pytest.mark.asyncio
async def test_mcp_fetch_jobs_from_source():
    # Fetch from Arbeitnow (public API)
    jobs = await fetch_jobs_from_source(source_name="arbeitnow", limit=2)
    assert isinstance(jobs, list)
    if jobs:
        assert "title" in jobs[0]
        assert "original_url" in jobs[0]


@pytest.mark.asyncio
async def test_mcp_ingest_and_application_assistant_flow():
    # 1. Save a sample job
    job_record = await save_discovered_job(
        title="Full Stack Python Developer",
        job_url="https://company.careers/jobs/py-909",
        source_platform="greenhouse",
        company_name="Apex Labs",
        company_domain="apexlabs.com",
        location="Remote",
        is_remote=True,
        skills_required=["Python", "FastAPI", "PostgreSQL"],
        description="Looking for an experienced engineer to scale backend APIs.",
    )
    job_id = job_record["id"]

    # 2. Match against profile
    match_res = await match_job_against_profile(
        job_id=job_id,
        full_name="Karan Aggarwal",
        email="karan@example.com",
        verified_skills=["Python", "FastAPI", "PostgreSQL"],
        verified_experience_years=4.0,
        target_titles=["Python Developer"],
    )
    assert match_res["match_score"] >= 60.0
    assert "Python" in match_res["matched_skills"]

    # 3. Generate application draft
    draft_res = await generate_application_draft(
        job_id=job_id,
        full_name="Karan Aggarwal",
        email="karan@example.com",
        verified_skills=["Python", "FastAPI", "PostgreSQL"],
        verified_experience_years=4.0,
    )
    assert draft_res["company_name"] == "Apex Labs"
    assert draft_res["submission_allowed"] is True
    assert "Karan Aggarwal" in draft_res["tailored_cover_letter"]

    # 4. Update status to shortlisted
    status_res = await update_job_application_status(
        job_id=job_id,
        new_status="shortlisted",
        notes="Reviewed and confirmed relevant.",
    )
    assert status_res["status"] == "shortlisted"
