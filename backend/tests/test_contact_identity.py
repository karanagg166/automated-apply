import pytest
from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.repositories.contact import ContactRepository
from backend.app.services.contact_enrichment.contact_identity import (
    ContactIdentityResolver,
    IdentityConflict,
)
from backend.tests.contact_enrichment_fakes import URL, person


@pytest.fixture
async def company(db_session):
    row = Company(
        name="Fictional Startup",
        domain="fictional.example.com",
        metadata_={"employee_count": 12},
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def test_legacy_no_email_contact_reconciles_new_email(db_session, company):
    legacy, _ = await ContactRepository(db_session).save_or_update_contact(
        company.id, "Alex Fictional", "Founder", linkedin_url=URL
    )
    result, created, conflicts = await ContactIdentityResolver(db_session).reconcile(
        company.id, person()
    )
    assert result.id == legacy.id and not created and not conflicts
    assert (
        result.email == "alex@fictional.example.com"
        and result.email_status == "provider_reported"
    )


async def test_cross_provider_changed_roles_preserve_evidence(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(company.id, person())
    second, created, _ = await resolver.reconcile(
        company.id,
        person(
            source="signalhire",
            role_title="Head of Engineering",
            provider_person_id="a" * 32,
        ),
    )
    assert first.id == second.id and not created
    evidence = (await db_session.scalars(select(ContactEvidence))).all()
    assert {e.observed_role for e in evidence} == {"CTO", "Head of Engineering"}
    assert {e.source for e in evidence} == {"apollo", "signalhire"}


async def test_same_email_compatible_name_no_url(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(company.id, person())
    other, created, _ = await resolver.reconcile(
        company.id, person(linkedin_url=None, source="signalhire")
    )
    assert other.id == first.id and not created


async def test_same_name_different_profiles_are_distinct(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(company.id, person(email=None))
    second, created, _ = await resolver.reconcile(
        company.id,
        person(email=None, linkedin_url="https://linkedin.com/in/other-alex"),
    )
    assert second.id != first.id and created


async def test_same_names_different_companies(db_session, company):
    other = Company(name="Other", domain="other.example.com")
    db_session.add(other)
    await db_session.flush()
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(company.id, person(email=None))
    second, _, _ = await resolver.reconcile(
        other.id, person(email=None, company_domain=other.domain)
    )
    assert first.id != second.id


async def test_weak_names_do_not_merge(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(
        company.id, person(email=None, linkedin_url=None, evidence_strength="weak")
    )
    second, created, _ = await resolver.reconcile(
        company.id, person(email=None, linkedin_url=None, evidence_strength="weak")
    )
    assert first.id != second.id and created


async def test_conflicting_email_preserved_for_review(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    first, _, _ = await resolver.reconcile(company.id, person())
    second, _, issues = await resolver.reconcile(
        company.id, person(email="different@fictional.example.com")
    )
    assert first.id == second.id and issues == ["conflicting_email"]
    assert second.email == "alex@fictional.example.com"
    assert second.metadata_["identity_review_required"]
    evidence = (await db_session.scalars(select(ContactEvidence))).all()
    assert {e.provenance["email"] for e in evidence} == {
        "alex@fictional.example.com",
        "different@fictional.example.com",
    }


async def test_incompatible_email_identity_requires_review(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    await resolver.reconcile(company.id, person())
    with pytest.raises(IdentityConflict):
        await resolver.reconcile(
            company.id, person(full_name="Different Person", linkedin_url=None)
        )


async def test_human_correction_preserved(db_session, company):
    resolver = ContactIdentityResolver(db_session)
    contact, _, _ = await resolver.reconcile(company.id, person())
    contact.human_corrected, contact.full_name, contact.role_title = (
        True,
        "Alex Corrected",
        "Engineering Manager",
    )
    await resolver.reconcile(
        company.id, person(role_title="CEO", email="another@fictional.example.com")
    )
    assert (
        contact.full_name == "Alex Corrected"
        and contact.role_title == "Engineering Manager"
    )
    assert contact.email == "alex@fictional.example.com"


async def test_role_email_not_attached_to_person(db_session, company):
    contact, _, _ = await ContactIdentityResolver(db_session).reconcile(
        company.id, person(email="careers@fictional.example.com")
    )
    assert contact.email is None and contact.email_status == "unknown"
    evidence = await db_session.scalar(select(ContactEvidence))
    assert (
        evidence.contact_id is None
        and evidence.evidence_type == "company_business_inbox"
    )
