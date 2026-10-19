"""Shared contact serialization and retention safeguards for REST and MCP."""

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.contact import Contact
from backend.app.services.contact_enrichment.ranking import rank_contact
from backend.app.services.contact_enrichment.verification import (
    email_observed_at,
    fresh,
)


def contact_output(contact, company, job=None):
    settings = get_settings()
    ranking = rank_contact(contact, company, job, settings.CONTACT_CACHE_TTL_DAYS)
    expired = contact.enrichment_source in {"apollo", "signalhire"} and not fresh(
        email_observed_at(contact), settings.CONTACT_RETENTION_DAYS
    )
    if expired:
        ranking.update(
            email_send_ready=False,
            manual_outreach_review_available=False,
            manual_linkedin_available=False,
        )
    return {
        "id": str(contact.id),
        "company_id": str(contact.company_id),
        "company": company.name,
        "full_name": contact.full_name,
        "role_title": contact.role_title,
        "linkedin_url": None if expired else contact.linkedin_url,
        "email": None if expired else contact.email,
        "email_status": "unknown" if expired else contact.email_status,
        "source": contact.enrichment_source,
        "legacy_confidence_score": float(contact.confidence_score or 0),
        "last_checked_at": contact.last_checked_at,
        "last_reviewed_at": contact.last_reviewed_at,
        "do_not_contact": contact.do_not_contact,
        "suppression_reason": contact.suppression_reason,
        "human_review_notes": contact.human_review_notes,
        "associated_job_ids": (contact.metadata_ or {}).get("job_ids", [])[:100],
        "retention_expired": expired,
        **ranking,
    }


async def get_contact(session, contact_id, lock=False):
    statement = select(Contact).where(Contact.id == contact_id)
    if lock:
        statement = statement.with_for_update()
    contact = await session.scalar(statement)
    if contact is None:
        raise HTTPException(404, "Contact not found")
    return contact
