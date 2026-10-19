"""FastMCP Server providing foundational AI tool endpoints for Job Pulse Agent."""

import uuid
from typing import Any

from backend.app.core.config import get_settings
from backend.app.db.session import get_db_context
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.contact import ContactRepository
from backend.app.repositories.job import JobRepository
from backend.app.services.application_assistant import (
    ApplicationAssistant,
    CandidateProfile,
)
from backend.app.services.credit_manager import CreditManager
from backend.app.services.email_candidate_generator import EmailCandidateGenerator
from backend.app.services.job_sources.factory import JobSourceFactory

settings = get_settings()


async def lookup_or_create_company(
    name: str,
    domain: str | None = None,
    linkedin_url: str | None = None,
) -> dict[str, Any]:
    """Look up an existing company in the database by domain/name, or register a new one.

    Args:
        name: Name of the company (e.g. 'Stripe')
        domain: Primary domain of the company (e.g. 'stripe.com')
        linkedin_url: Optional LinkedIn company page URL

    Returns:
        Structured company record with ID, domain, and known email pattern.
    """
    async with get_db_context() as session:
        repo = CompanyRepository(session)
        company, was_created = await repo.get_or_create(
            name=name,
            domain=domain,
            linkedin_url=linkedin_url,
        )
        return {
            "id": str(company.id),
            "name": company.name,
            "domain": company.domain,
            "linkedin_url": company.linkedin_url,
            "email_pattern": company.email_pattern,
            "is_catch_all": company.is_catch_all,
            "was_created": was_created,
        }


async def get_cached_company_contacts(
    company_id: str,
    role_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve previously discovered professional contacts (recruiters, engineers, managers) for a company.

    Args:
        company_id: The UUID of the company to query.
        role_filter: Optional substring filter for role title (e.g. 'recruiter', 'manager', 'talent').

    Returns:
        List of cached contacts from PostgreSQL.
    """
    async with get_db_context() as session:
        repo = ContactRepository(session)
        cid = uuid.UUID(company_id)
        contacts = await repo.get_cached_contacts_for_company(
            cid, role_filter=role_filter
        )
        return [
            {
                "id": str(c.id),
                "full_name": c.full_name,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "role_title": c.role_title,
                "linkedin_url": c.linkedin_url,
                "email": c.email,
                "email_status": c.email_status,
                "confidence_score": float(c.confidence_score),
                "enrichment_source": c.enrichment_source,
            }
            for c in contacts
        ]


def generate_company_email_candidates(
    first_name: str,
    last_name: str,
    domain: str,
    known_pattern: str | None = None,
) -> list[dict[str, Any]]:
    """Generate potential corporate email address candidates based on standard naming patterns.

    CRITICAL SAFETY NOTICE:
    Generated addresses are mathematical pattern candidates. They are NOT confirmed mailboxes
    and must NEVER be used for automated cold outreach without verification or human approval.

    Args:
        first_name: First name of the person (e.g. 'Alex')
        last_name: Last name of the person (e.g. 'Smith')
        domain: Company domain (e.g. 'company.com')
        known_pattern: Optional known company pattern (e.g. '{first}.{last}@{domain}')

    Returns:
        List of candidate objects with email, pattern_used, status='candidate', and safety disclaimer.
    """
    candidates = EmailCandidateGenerator.generate_candidates(
        first_name=first_name,
        last_name=last_name,
        domain=domain,
        known_pattern=known_pattern,
    )
    return [c.model_dump() for c in candidates]


async def save_discovered_job(
    title: str,
    job_url: str,
    source_platform: str,
    company_name: str,
    company_domain: str | None = None,
    location: str | None = None,
    is_remote: bool = False,
    experience_level: str | None = None,
    salary_range: str | None = None,
    skills_required: list[str] | None = None,
    description: str | None = None,
    match_score: float | None = None,
    match_explanation: str | None = None,
) -> dict[str, Any]:
    """Save or update a discovered job opening with automatic deduplication by URL.

    Args:
        title: Job position title
        job_url: Canonical job listing URL
        source_platform: Discovery platform (e.g. 'gmail_alert', 'greenhouse', 'manual')
        company_name: Employer name
        company_domain: Optional company domain
        location: Job location
        is_remote: Whether the role allows remote work
        experience_level: e.g. 'entry', 'junior', 'mid'
        salary_range: Optional compensation range
        skills_required: List of technical skill keywords
        description: Job description text
        match_score: Multi-factor match score (0-100)
        match_explanation: Rationale for matching score

    Returns:
        Saved job record with ID, company ID, and deduplication status.
    """
    async with get_db_context() as session:
        company_repo = CompanyRepository(session)
        job_repo = JobRepository(session)

        company, _ = await company_repo.get_or_create(
            name=company_name,
            domain=company_domain,
        )

        job, was_created = await job_repo.save_or_update_job(
            title=title,
            job_url=job_url,
            source_platform=source_platform,
            company_id=company.id,
            location=location,
            is_remote=is_remote,
            experience_level=experience_level,
            salary_range=salary_range,
            skills_required=skills_required or [],
            description=description,
            match_score=match_score,
            match_explanation=match_explanation,
        )
        return {
            "id": str(job.id),
            "company_id": str(company.id),
            "company_name": company.name,
            "title": job.title,
            "job_url": job.job_url,
            "status": job.status,
            "was_created": was_created,
        }


async def check_api_credits_status() -> dict[str, Any]:
    """Check remaining API credits, quota limits, and cooldown status across all configured external providers.

    Returns:
        Summary of provider budgets, active keys, and remaining quotas.
    """
    async with get_db_context() as session:
        manager = CreditManager(session)
        status = await manager.get_credit_status()
        return status.model_dump(mode="json")


async def check_job_source_connection(source_name: str) -> dict[str, Any]:
    """Perform a safe, read-only connectivity test for a job portal or source adapter.

    Args:
        source_name: Name of the job source ('greenhouse', 'remotive', 'arbeitnow', 'hacker_news', 'apify', 'gmail_alert', 'naukri', etc.)

    Returns:
        Structured test result with status ('passed'|'failed'|'not_attempted'), sample count, and details.
    """
    adapter = JobSourceFactory.get_adapter(source_name)
    return await adapter.test_connection()


async def fetch_jobs_from_source(
    source_name: str,
    query: str = "software engineer",
    location: str = "remote",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Fetch live or catalog job postings from an authorized job source without persisting.

    Args:
        source_name: Job source adapter identifier (e.g. 'greenhouse', 'remotive', 'arbeitnow', 'hacker_news', 'apify')
        query: Search keywords or role title
        location: Target location or remote filter
        limit: Maximum number of postings to retrieve (default: 5, safety capped)

    Returns:
        List of normalized job listings conforming to unified schema.
    """
    capped_limit = min(max(limit, 1), 25)
    adapter = JobSourceFactory.get_adapter(source_name)
    jobs = await adapter.fetch_jobs(
        search_query=query, location=location, limit=capped_limit
    )
    return [j.model_dump(mode="json") for j in jobs]


async def ingest_jobs_from_source(
    source_name: str,
    query: str = "software engineer",
    location: str = "remote",
    limit: int = 5,
) -> dict[str, Any]:
    """Fetch and ingest job postings into the isolated 'job_agent' schema with deduplication.

    Args:
        source_name: Source name ('greenhouse', 'remotive', 'arbeitnow', 'hacker_news', 'apify')
        query: Search keywords
        location: Location filter
        limit: Max jobs to ingest

    Returns:
        Ingestion summary with inserted, updated, and skipped counts.
    """
    raise PermissionError(
        "Use bearer-protected POST /api/v1/discovery/runs for source execution and ingestion"
    )


async def match_job_against_profile(
    job_id: str,
    full_name: str,
    email: str,
    verified_skills: list[str],
    verified_experience_years: float | None = None,
    preferred_locations: list[str] | None = None,
    target_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate an explainable match score (0-100) between a discovered job and a verified candidate profile.

    Args:
        job_id: UUID of the job opening in PostgreSQL
        full_name: Candidate full name
        email: Candidate email
        verified_skills: Real technical skills possessed by the candidate
        verified_experience_years: Actual years of experience
        preferred_locations: Preferred work locations
        target_titles: Target role titles

    Returns:
        Explainable match score, matched skills, missing skills, and detailed rationale.
    """
    profile = CandidateProfile(
        full_name=full_name,
        email=email,
        verified_skills=verified_skills,
        verified_experience_years=verified_experience_years,
        preferred_locations=preferred_locations or [],
        target_titles=target_titles or [],
    )
    async with get_db_context() as session:
        job_repo = JobRepository(session)
        job = await job_repo.get_by_id(uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job with ID '{job_id}' not found")
        assistant = ApplicationAssistant(session)
        match_res = assistant.calculate_match(job, profile)
        return match_res.model_dump(mode="json")


async def generate_application_draft(
    job_id: str,
    full_name: str,
    email: str,
    verified_skills: list[str],
    verified_experience_years: float | None = None,
    phone: str | None = None,
    linkedin_url: str | None = None,
    github_url: str | None = None,
) -> dict[str, Any]:
    """Generate human-in-the-loop application materials (cover letter & Q&A) with ZERO fact fabrication.

    CRITICAL SAFETY RULES:
    1. LinkedIn automated application submission is strictly prohibited.
    2. All statements are derived exclusively from verified candidate inputs.
    3. Human confirmation is mandatory before applying.

    Args:
        job_id: UUID of the job opening in PostgreSQL
        full_name: Candidate full name
        email: Candidate email
        verified_skills: Verified candidate skills
        verified_experience_years: Verified years of experience
        phone: Optional contact phone
        linkedin_url: Optional LinkedIn profile URL
        github_url: Optional GitHub profile URL

    Returns:
        Application draft containing tailored letter, prepared answers, and direct apply link.
    """
    profile = CandidateProfile(
        full_name=full_name,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        github_url=github_url,
        verified_skills=verified_skills,
        verified_experience_years=verified_experience_years,
    )
    async with get_db_context() as session:
        job_repo = JobRepository(session)
        company_repo = CompanyRepository(session)
        job = await job_repo.get_by_id(uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job with ID '{job_id}' not found")

        company_name = "Hiring Team"
        if job.company_id:
            company = await company_repo.get_by_id(job.company_id)
            if company:
                company_name = company.name

        assistant = ApplicationAssistant(session)
        draft = assistant.generate_draft_application(job, company_name, profile)
        return draft.model_dump(mode="json")


async def update_job_application_status(
    job_id: str,
    new_status: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update job application status upon human review and manual submission confirmation.

    Allowed statuses: 'discovered', 'reviewed', 'shortlisted', 'applied', 'rejected', 'archived'.

    Args:
        job_id: UUID of the job in PostgreSQL
        new_status: Target status string
        notes: Optional audit notes or interview feedback

    Returns:
        Updated job record summary.
    """
    async with get_db_context() as session:
        assistant = ApplicationAssistant(session)
        updated_job = await assistant.update_application_status(
            job_id, new_status, notes=notes
        )
        return {
            "job_id": str(updated_job.id),
            "status": updated_job.status,
            "title": updated_job.title,
            "updated_at": updated_job.updated_at.isoformat()
            if updated_job.updated_at
            else None,
        }


# The single authoritative instance registers only Phase 4A protected tools.
from backend.app.mcp.registry import mcp as mcp
