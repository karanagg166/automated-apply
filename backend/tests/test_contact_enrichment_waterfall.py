import pytest
from sqlalchemy import func, select

from backend.app.db.session import get_session_factory
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEnrichmentRun, ContactEvidence
from backend.app.models.discovery import DiscoveredPerson, DiscoveryReservation, now
from backend.app.services.contact_enrichment.schemas import EnrichInput, State
from backend.app.services.contact_enrichment.service import ContactEnrichmentService
from backend.tests.contact_enrichment_fakes import (
    URL,
    FakeApollo,
    FakeSignal,
    person,
    settings,
)


@pytest.fixture
async def prepared(db_session):
    company = Company(
        name="Fictional Startup",
        domain="fictional.example.com",
        metadata_={"employee_count": 12},
    )
    db_session.add(company)
    await db_session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Alex Fictional",
        role_title="CTO",
        linkedin_url=URL,
    )
    db_session.add(contact)
    await db_session.commit()
    return company, contact


def service(session, apollo=None, signal=None, config=None):
    return ContactEnrichmentService(
        session,
        get_session_factory(),
        settings=config or settings(),
        providers={
            "apollo": apollo or FakeApollo(),
            "signalhire": signal or FakeSignal(),
        },
    )


async def test_no_paid_calls_without_authorization_and_preview_is_read_only(
    db_session, prepared
):
    company, contact = prepared
    apollo, signal = FakeApollo(), FakeSignal()
    svc = service(db_session, apollo, signal)
    preview = await svc.preview(company.id, EnrichInput(allow_paid=True))
    assert preview["billable_calls"] == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(ContactEnrichmentRun))
        == 0
    )
    run = await svc.enrich(company.id, EnrichInput(providers=["apollo", "signalhire"]))
    assert (
        not apollo.calls and not signal.calls and run.contact_ids == [str(contact.id)]
    )


@pytest.mark.parametrize(
    "email,strong", [("alex@fictional.example.com", False), (None, True)]
)
async def test_reliable_cache_skips_paid(db_session, prepared, email, strong):
    company, contact = prepared
    contact.email, contact.email_status, contact.last_checked_at = (
        email,
        "verified" if email else "unknown",
        now(),
    )
    contact.metadata_ = {"evidence_strength": "strong" if strong else "moderate"}
    await db_session.commit()
    apollo = FakeApollo()
    await service(db_session, apollo).enrich(company.id, EnrichInput(allow_paid=True))
    assert not apollo.calls


async def test_apollo_success_avoids_fallback_and_deduplicates(db_session, prepared):
    company, contact = prepared
    apollo, signal = FakeApollo(), FakeSignal()
    run = await service(db_session, apollo, signal).enrich(
        company.id,
        EnrichInput(
            allow_paid=True, providers=["apollo", "signalhire"], allow_fallback=True
        ),
    )
    assert len(apollo.calls) == 1 and not signal.calls and run.state == "completed"
    assert contact.email_status == "provider_reported"
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 1
    assert (
        run.usage[0]["reserved_estimate"] == 1
        and run.usage[0]["confirmed_provider_credits"] is None
    )


@pytest.mark.parametrize(
    "state",
    [
        State.NOT_FOUND,
        State.FAILED,
        State.UNCERTAIN,
        State.AUTHORIZATION_REQUIRED,
        State.RATE_LIMITED,
    ],
)
async def test_no_empty_or_error_cascade(db_session, prepared, state):
    company, _ = prepared
    apollo = FakeApollo()
    apollo.response = apollo.result(state, errors=["Sanitized provider outcome"])
    signal = FakeSignal()
    run = await service(db_session, apollo, signal).enrich(
        company.id,
        EnrichInput(
            allow_paid=True, providers=["apollo", "signalhire"], allow_fallback=True
        ),
    )
    assert len(apollo.calls) == 1 and not signal.calls and run.state == state


@pytest.mark.parametrize("allowed", [True, False])
async def test_missing_email_fallback_requires_separate_opt_in(
    db_session, prepared, allowed
):
    company, contact = prepared
    apollo = FakeApollo()
    apollo.response = apollo.result(
        State.COMPLETED, contacts=[person(email=None, email_status="unknown")]
    )
    signal = FakeSignal()
    await service(db_session, apollo, signal).enrich(
        company.id,
        EnrichInput(
            allow_paid=True, providers=["apollo", "signalhire"], allow_fallback=allowed
        ),
    )
    assert len(signal.calls) == int(allowed)


async def test_restart_or_new_run_does_not_repeat_uncertain_billable_call(
    db_session, prepared
):
    company, _ = prepared
    apollo = FakeApollo()
    apollo.response = apollo.result(State.UNCERTAIN)
    await service(db_session, apollo).enrich(company.id, EnrichInput(allow_paid=True))
    await service(db_session, apollo).enrich(company.id, EnrichInput(allow_paid=True))
    assert len(apollo.calls) == 1
    reservations = (await db_session.scalars(select(DiscoveryReservation))).all()
    assert len(reservations) == 1 and float(reservations[0].reserved) == 1


async def test_idempotency_key_reuses_run_and_rejects_different_request(
    db_session, prepared
):
    from backend.app.services.contact_enrichment.contact_identity import (
        IdentityConflict,
    )

    company, _ = prepared
    apollo = FakeApollo()
    svc = service(db_session, apollo)
    request = EnrichInput(allow_paid=True, idempotency_key="fictional-idempotency-001")
    first = await svc.enrich(company.id, request)
    second = await svc.enrich(company.id, request)
    assert first.id == second.id and len(apollo.calls) == 1
    with pytest.raises(IdentityConflict):
        await svc.enrich(company.id, request.model_copy(update={"max_people": 2}))


@pytest.mark.parametrize(
    "config",
    [
        settings(APOLLO_MONTHLY_LIMIT=0),
        settings(APOLLO_PER_RUN_LIMIT=0),
        settings(APOLLO_CREDITS_PER_LOOKUP=0),
    ],
)
async def test_budget_and_unknown_cost_prevent_execution(db_session, prepared, config):
    company, _ = prepared
    apollo = FakeApollo()
    run = await service(db_session, apollo, config=config).enrich(
        company.id, EnrichInput(allow_paid=True)
    )
    assert not apollo.calls and run.errors


async def test_discovered_people_bridge_and_candidates_remain_separate(
    db_session, prepared
):
    company, contact = prepared
    db_session.add(
        DiscoveredPerson(
            company_id=company.id,
            name="Alex Fictional",
            role="CTO",
            linkedin_url=URL,
            evidence_url="https://fictional.example.com/team",
            source="public_search",
            verification_status="public_evidence_unverified",
        )
    )
    await db_session.commit()
    run = await service(db_session).enrich(
        company.id, EnrichInput(include_candidates=True)
    )
    assert run.contact_ids == [str(contact.id)] and contact.email is None
    assert contact.email_status == "unknown"
    assert run.counts["candidate_research"][0]["candidates"][0]["status"] == "candidate"
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 1
    evidence = await db_session.scalar(select(ContactEvidence))
    assert evidence.provenance["discovered_person_id"] is not None


async def test_suppressed_contact_skips_paid_and_candidates(db_session, prepared):
    company, contact = prepared
    contact.do_not_contact = True
    await db_session.commit()
    apollo = FakeApollo()
    run = await service(db_session, apollo).enrich(
        company.id, EnrichInput(allow_paid=True, include_candidates=True)
    )
    assert not apollo.calls and not run.counts["candidate_research"]


async def test_conflicting_provider_profile_is_preserved_and_blocks_fallback(
    db_session, prepared
):
    company, contact = prepared
    apollo, signal = FakeApollo(), FakeSignal()
    apollo.response = apollo.result(
        State.COMPLETED,
        contacts=[
            person(linkedin_url="https://linkedin.com/in/another-person", email=None)
        ],
    )
    run = await service(db_session, apollo, signal).enrich(
        company.id,
        EnrichInput(
            allow_paid=True, providers=["apollo", "signalhire"], allow_fallback=True
        ),
    )
    assert contact.metadata_["identity_review_required"] and not signal.calls
    assert run.errors
    evidence = await db_session.scalar(
        select(ContactEvidence).where(
            ContactEvidence.evidence_type == "identity_conflict"
        )
    )
    assert evidence.provenance["full_name"] == "Alex Fictional"


async def test_discovered_observation_keeps_original_age(db_session, prepared):
    from datetime import timedelta

    company, contact = prepared
    old = now() - timedelta(days=100)
    db_session.add(
        DiscoveredPerson(
            company_id=company.id,
            name=contact.full_name,
            role="CTO",
            linkedin_url=URL,
            evidence_url="https://fictional.example.com/team",
            source="public_search",
            verification_status="unverified",
            observed_at=old,
        )
    )
    await db_session.commit()
    await service(db_session).enrich(company.id, EnrichInput())
    assert contact.last_checked_at.replace(tzinfo=old.tzinfo) == old
