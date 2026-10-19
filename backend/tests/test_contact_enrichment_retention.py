from datetime import timedelta

from backend.app.db.session import get_session_factory
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.services.contact_enrichment.ranking import rank_contact
from backend.app.services.contact_enrichment.retention import prune_provider_data
from backend.app.services.contact_enrichment.schemas import EnrichInput
from backend.app.services.contact_enrichment.service import ContactEnrichmentService
from backend.tests.contact_enrichment_fakes import URL, FakeApollo, FakeSignal, settings


async def test_expired_provider_data_pruned_and_suppression_retained(db_session):
    company = Company(name="Fictional", domain="fictional.example.com")
    db_session.add(company)
    await db_session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Alex Fictional",
        role_title="CTO",
        linkedin_url=URL,
        email="alex@fictional.example.com",
        email_status="provider_reported",
        last_checked_at=now() - timedelta(days=100),
        enrichment_source="apollo",
        do_not_contact=True,
    )
    db_session.add(contact)
    await db_session.flush()
    db_session.add(
        ContactEvidence(
            company_id=company.id,
            contact_id=contact.id,
            source="apollo",
            evidence_type="professional_observation",
            collected_at=now() - timedelta(days=100),
            expires_at=now() - timedelta(days=70),
            provenance={"email": contact.email},
        )
    )
    await db_session.flush()
    result = await prune_provider_data(db_session)
    assert result["contacts_pruned"] == 1 and result["evidence_deleted"] == 1
    assert (
        contact.do_not_contact
        and contact.email is None
        and contact.linkedin_url is None
    )
    assert not rank_contact(contact, company)["email_send_ready"]


async def test_reviewed_public_business_evidence_avoids_paid_lookup(db_session):
    company = Company(name="Fictional", domain="fictional.example.com")
    db_session.add(company)
    await db_session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Alex Fictional",
        role_title="CTO",
        linkedin_url=URL,
    )
    db_session.add(contact)
    await db_session.flush()
    db_session.add(
        ContactEvidence(
            company_id=company.id,
            contact_id=contact.id,
            source="manual",
            evidence_type="public_business_contact",
            evidence_url="https://fictional.example.com/team",
            expires_at=now() + timedelta(days=10),
            user_confirmed=True,
            strength="strong",
            provenance={
                "email": "alex@fictional.example.com",
                "email_kind": "person_specific",
            },
        )
    )
    await db_session.commit()
    apollo = FakeApollo()
    service = ContactEnrichmentService(
        db_session,
        get_session_factory(),
        settings(),
        {"apollo": apollo, "signalhire": FakeSignal()},
    )
    run = await service.enrich(company.id, EnrichInput(allow_paid=True))
    assert (
        not apollo.calls
        and contact.email_status == "provider_reported"
        and not run.usage
    )


async def test_pruned_suppression_cannot_reappear_through_discovery(db_session):
    from backend.app.services.contact_enrichment.contact_identity import (
        ContactIdentityResolver,
    )
    from backend.tests.contact_enrichment_fakes import person

    company = Company(name="Fictional", domain="fictional.example.com")
    db_session.add(company)
    await db_session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Alex Fictional",
        role_title="CTO",
        linkedin_url=URL,
        email="alex@fictional.example.com",
        email_status="provider_reported",
        last_checked_at=now() - timedelta(days=100),
        enrichment_source="apollo",
        do_not_contact=True,
    )
    db_session.add(contact)
    await db_session.flush()
    original_id = contact.id
    await prune_provider_data(db_session)
    same, created, issues = await ContactIdentityResolver(db_session).reconcile(
        company.id, person()
    )
    assert same.id == original_id and not created and same.do_not_contact
    assert same.email is None and issues == ["suppressed"]
