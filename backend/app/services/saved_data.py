"""Shared, bounded, non-billable saved-data access for API and MCP."""

from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.repositories.job import JobRepository
from backend.app.schemas.job import JobRead
from backend.app.services.application_assistant import ApplicationAssistant
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.services.contact_enrichment.verification import fresh
from backend.app.services.contact_read import contact_output, get_contact
from backend.app.services.job_sources.registry import source_registry


class SavedDataService:
    def __init__(self, session):
        self.session = session

    def sources(self):
        return [s.model_dump() for s in source_registry().values()]

    async def jobs(self, limit=50, offset=0, status=None):
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("pagination_out_of_bounds")
        if status is not None and status not in {
            "discovered",
            "reviewed",
            "shortlisted",
            "applied",
            "rejected",
            "archived",
        }:
            raise ValueError("invalid_job_status")
        return [
            JobRead.model_validate(j).model_dump(mode="json")
            for j in await JobRepository(self.session).list_jobs(limit, offset, status)
        ]

    async def job(self, job_id):
        job = await JobRepository(self.session).get_by_id(job_id)
        if job is None:
            raise LookupError("Job not found")
        return JobRead.model_validate(job).model_dump(mode="json")

    async def match(self, job_id):
        profile = await CandidateProfileService(self.session).to_application_profile()
        job = await JobRepository(self.session).get_by_id(job_id)
        if job is None:
            raise LookupError("Job not found")
        return (
            ApplicationAssistant(self.session)
            .calculate_match(job, profile)
            .model_dump(mode="json")
        )

    async def company(self, company_id):
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Company not found")
        return {
            "id": str(company.id),
            "name": company.name,
            "domain": company.domain,
            "linkedin_url": company.linkedin_url,
            "intelligence": company.metadata_,
        }

    async def contacts(self, company_id, limit=25):
        if not 1 <= limit <= 100:
            raise ValueError("pagination_out_of_bounds")
        company = await self.session.get(Company, company_id)
        if not company:
            raise LookupError("Company not found")
        contacts = (
            await self.session.scalars(
                select(Contact)
                .where(
                    Contact.company_id == company_id, Contact.do_not_contact.is_(False)
                )
                .order_by(Contact.id)
                .limit(1000)
            )
        ).all()
        return sorted(
            [contact_output(c, company) for c in contacts],
            key=lambda x: -x["ordering_score"],
        )[:limit]

    async def contact_details(self, contact_id):
        contact = await get_contact(self.session, contact_id)
        company = await self.session.get(Company, contact.company_id)
        evidence = (
            await self.session.scalars(
                select(ContactEvidence)
                .where(ContactEvidence.contact_id == contact_id)
                .order_by(ContactEvidence.collected_at.desc())
                .limit(100)
            )
        ).all()
        return {
            **contact_output(contact, company),
            "evidence": [
                {
                    "id": str(e.id),
                    "source": e.source,
                    "type": e.evidence_type,
                    "url": e.evidence_url,
                    "observed_role": e.observed_role,
                    "observed_company": e.observed_company,
                    "provider_verification_claim": e.provider_verification_claim,
                    "strength": e.strength,
                    "collected_at": e.collected_at,
                    "expires_at": e.expires_at,
                    "user_confirmed": e.user_confirmed,
                    "provenance": e.provenance
                    if fresh(e.expires_at, 0)
                    else {"expired": True},
                }
                for e in evidence
            ],
        }
