"""FastMCP Server providing foundational AI tool endpoints for Job Pulse Agent."""

import uuid
from typing import Any
from fastmcp import FastMCP
from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.db.session import get_db_context
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.job import JobRepository
from backend.app.repositories.contact import ContactRepository
from backend.app.services.credit_manager import CreditManager
from backend.app.services.email_candidate_generator import EmailCandidateGenerator

settings = get_settings()
mcp = FastMCP(settings.FASTMCP_SERVER_NAME)


@mcp.tool()
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


@mcp.tool()
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
        contacts = await repo.get_cached_contacts_for_company(cid, role_filter=role_filter)
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def check_api_credits_status() -> dict[str, Any]:
    """Check remaining API credits, quota limits, and cooldown status across all configured external providers.

    Returns:
        Summary of provider budgets, active keys, and remaining quotas.
    """
    async with get_db_context() as session:
        manager = CreditManager(session)
        status = await manager.get_credit_status()
        return status.model_dump(mode="json")
