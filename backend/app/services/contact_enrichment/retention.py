"""Explicit maintenance, never startup/scheduled work. Suppression survives pruning."""

import hashlib
from datetime import timedelta, timezone

from sqlalchemy import delete, select

from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import (
    ContactEnrichmentRun,
    ContactEvidence,
    ContactIdentity,
)
from backend.app.models.discovery import now
from backend.app.services.contact_enrichment.contact_identity import normalized_url
from backend.app.services.contact_enrichment.verification import email_observed_at


async def prune_provider_data(session, retention_days=90):
    cutoff = now() - timedelta(days=retention_days)
    contacts = (
        await session.scalars(
            select(Contact).where(
                Contact.enrichment_source.in_(["apollo", "signalhire"]),
                Contact.human_corrected.is_(False),
            )
        )
    ).all()
    for company_id in sorted({c.company_id for c in contacts}, key=str):
        await session.scalar(
            select(Company.id).where(Company.id == company_id).with_for_update()
        )
    for contact in contacts:
        await session.refresh(contact)
    contacts = [c for c in contacts if not c.human_corrected]
    contacts = [
        c
        for c in contacts
        if (
            email_observed_at(c) is None
            or email_observed_at(c).replace(tzinfo=timezone.utc) < cutoff
        )
    ]
    for contact in contacts:
        suppression_keys = []
        profile = normalized_url(contact.linkedin_url)
        if profile:
            suppression_keys.append(
                ("suppressed_linkedin", hashlib.sha256(profile.encode()).hexdigest())
            )
        if contact.email:
            suppression_keys.append(
                (
                    "suppressed_email",
                    hashlib.sha256(contact.email.casefold().encode()).hexdigest(),
                )
            )
        await session.execute(
            delete(ContactIdentity).where(
                ContactIdentity.contact_id == contact.id,
                ~ContactIdentity.namespace.like("suppressed_%"),
            )
        )
        for namespace, key in suppression_keys:
            existing = await session.scalar(
                select(ContactIdentity.id).where(
                    ContactIdentity.company_id == contact.company_id,
                    ContactIdentity.namespace == namespace,
                    ContactIdentity.identity_key == key,
                )
            )
            if not existing:
                session.add(
                    ContactIdentity(
                        company_id=contact.company_id,
                        contact_id=contact.id,
                        namespace=namespace,
                        identity_key=key,
                    )
                )
        # Keep a suppressed tombstone and audit references; discard professional fields.
        # Durable lookup hashes survive so pruning never reauthorizes a paid request.
        contact.full_name, contact.role_title = (
            "Removed professional contact",
            "Unknown",
        )
        contact.first_name = contact.last_name = contact.email = (
            contact.linkedin_url
        ) = None
        contact.email_status, contact.metadata_, contact.do_not_contact = (
            "unknown",
            {},
            True,
        )
        contact.suppression_reason = (
            contact.suppression_reason or "Provider retention expired"
        )

    expired = await session.execute(
        delete(ContactEvidence).where(ContactEvidence.collected_at < cutoff)
    )
    runs = (
        await session.scalars(
            select(ContactEnrichmentRun).where(ContactEnrichmentRun.started_at < cutoff)
        )
    ).all()
    for run in runs:
        run.counts = {k: v for k, v in run.counts.items() if k != "candidate_research"}
    await session.flush()
    return {
        "contacts_pruned": len(contacts),
        "evidence_deleted": expired.rowcount,
        "runs_redacted": len(runs),
    }
