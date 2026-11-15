"""Repository for Contact entity operations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.contact import Contact
from backend.app.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    """Data access repository for professional contacts."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Contact, session)

    async def get_by_company_and_email(self, company_id: UUID, email: str) -> Contact | None:
        """Find contact by company ID and email."""
        if not email:
            return None
        cleaned = email.strip().lower()
        stmt = select(Contact).where(
            Contact.company_id == company_id,
            Contact.email == cleaned,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_cached_contacts_for_company(
        self,
        company_id: UUID,
        role_filter: str | None = None,
    ) -> list[Contact]:
        """Retrieve previously discovered contacts for a company from local database."""
        stmt = select(Contact).where(Contact.company_id == company_id).order_by(Contact.confidence_score.desc())
        if role_filter:
            stmt = stmt.where(Contact.role_title.ilike(f"%{role_filter.strip()}%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_or_update_contact(
        self,
        company_id: UUID,
        full_name: str,
        role_title: str,
        first_name: str | None = None,
        last_name: str | None = None,
        linkedin_url: str | None = None,
        email: str | None = None,
        email_status: str = "unknown",
        confidence_score: float = 0.0,
        enrichment_source: str | None = None,
        last_verified_at: datetime | None = None,
    ) -> tuple[Contact, bool]:
        """Save a new contact or update existing contact details if email matches."""
        existing = None
        if email:
            existing = await self.get_by_company_and_email(company_id, email)

        if existing:
            # Update verification details if more confident source provided
            if confidence_score > existing.confidence_score:
                existing.confidence_score = confidence_score
                existing.email_status = email_status
                existing.enrichment_source = enrichment_source
                if last_verified_at:
                    existing.last_verified_at = last_verified_at
            if linkedin_url and not existing.linkedin_url:
                existing.linkedin_url = linkedin_url
            await self.session.flush()
            return existing, False

        new_contact = await self.create(
            company_id=company_id,
            full_name=full_name.strip(),
            first_name=first_name.strip() if first_name else None,
            last_name=last_name.strip() if last_name else None,
            role_title=role_title.strip(),
            linkedin_url=linkedin_url,
            email=email.strip().lower() if email else None,
            email_status=email_status,
            confidence_score=confidence_score,
            enrichment_source=enrichment_source,
            last_verified_at=last_verified_at,
        )
        return new_contact, True
