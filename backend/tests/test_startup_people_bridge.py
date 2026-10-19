from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from backend.app.db.session import get_session_factory
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.services.discovery_budget import DiscoveryBudget
from backend.app.services.people_discovery.base import (
    OfficialPersonEvidence,
    PeopleQuery,
)
from backend.app.services.people_discovery.public_search import PublicSearchAdapter
from backend.app.services.people_discovery.service import PeopleDiscoveryService
from backend.app.services.saved_data import SavedDataService
from backend.tests.discovery_fakes import FakeBudget, settings


def official(**changes):
    values = dict(
        full_name="Alex Fictional",
        role_title="CTO",
        evidence_url="https://fictional.example/team",
        professional_url="https://fictional.example/team/alex",
        permission_evidence_url="https://fictional.example/permission",
        observed_at=now(),
        human_confirmed=True,
    )
    values.update(changes)
    return OfficialPersonEvidence(**values)


def query(**changes):
    values = dict(
        company_name="Fictional Robotics",
        company_domain="fictional.example",
        source="manual",
        permission_confirmed=True,
        official_people=[official()],
    )
    values.update(changes)
    return PeopleQuery(**values)


@pytest.mark.asyncio
async def test_official_evidence_dedup_suppression_and_no_invented_email(db_session):
    service = PeopleDiscoveryService(
        db_session, DiscoveryBudget(get_session_factory()), settings()
    )
    result = await service.search(query())
    contact_id = UUID(result["people"][0]["contact_id"])
    contact = await db_session.get(Contact, contact_id)
    assert contact.email is None and contact.email_status == "unknown"
    await service.search(
        query(
            official_people=[official(evidence_url="https://fictional.example/about")]
        )
    )
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 1
    contact.do_not_contact = True
    contact.human_corrected = True
    contact.role_title = "Owner corrected role"
    await service.search(query())
    assert contact.do_not_contact and contact.role_title == "Owner corrected role"
    assert await SavedDataService(db_session).contacts(contact.company_id) == []
    evidence = await db_session.scalar(
        select(ContactEvidence).where(ContactEvidence.contact_id == contact_id)
    )
    assert (
        evidence.provenance["permission_evidence_url"]
        == "https://fictional.example/permission"
    )


@pytest.mark.asyncio
async def test_same_name_different_employers_never_merge(db_session):
    service = PeopleDiscoveryService(
        db_session, DiscoveryBudget(get_session_factory()), settings()
    )
    await service.search(query())
    other = official(
        evidence_url="https://other.example/team",
        professional_url="https://other.example/team/alex",
    )
    result = await service.search(
        query(
            company_name="Other Fictional",
            company_domain="other.example",
            official_people=[other],
        )
    )
    assert result["status"] == "success"
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 2


@pytest.mark.asyncio
async def test_ambiguous_and_stale_official_evidence(db_session):
    service = PeopleDiscoveryService(
        db_session, DiscoveryBudget(get_session_factory()), settings()
    )
    result = await service.search(
        query(
            official_people=[
                official(human_confirmed=False, observed_at=now() - timedelta(days=100))
            ]
        )
    )
    contact = await db_session.get(Contact, UUID(result["people"][0]["contact_id"]))
    result = (await SavedDataService(db_session).contacts(contact.company_id))[0]
    assert result["confidence"] == "requires_review"
    assert not result["email_send_ready"]
    mismatch = await service.search(
        query(official_people=[official(evidence_url="https://other.example/team")])
    )
    assert mismatch["status"] == "partial"
    with pytest.raises(ValueError):
        await service.search(query(permission_confirmed=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["public_profiles", "official_company"])
async def test_retention_rights_required_before_search_credits(db_session, mode):
    budget = FakeBudget()
    result = await PeopleDiscoveryService(
        db_session,
        budget,
        settings(PEOPLE_SEARCH_ENABLED=True, SERPER_API_KEY="fictional"),
    ).search(PeopleQuery(company_name="Fictional", research_mode=mode, allow_paid=True))
    assert result["status"] == "authentication_required" and not budget.calls


@pytest.mark.asyncio
async def test_official_search_only_fixed_provider_no_linkedin_requests(db_session):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Alex Fictional - CTO Fictional Robotics",
                        "link": "https://fictional.example/team/alex",
                        "snippet": "CTO at Fictional Robotics",
                    },
                    {
                        "title": "Alex Fictional - CTO Fictional Robotics",
                        "link": "https://linkedin.com/in/fictional",
                        "snippet": "CTO",
                    },
                ]
            },
        )

    config = settings(
        PEOPLE_SEARCH_ENABLED=True,
        SERPER_API_KEY="fictional",
        PUBLIC_SEARCH_RIGHTS_REVIEWED=True,
        PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL="https://fictional.example/permission",
        PUBLIC_SEARCH_ALLOWED_DOMAINS={
            "fictional.example": "https://fictional.example/permission"
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PeopleDiscoveryService(
            db_session, FakeBudget(), config, PublicSearchAdapter("fictional", client)
        ).search(
            PeopleQuery(
                company_name="Fictional Robotics",
                company_domain="fictional.example",
                research_mode="official_company",
                allow_paid=True,
            )
        )
    assert len(requests) == 1 and all(
        r.url.host == "google.serper.dev" for r in requests
    )
    assert (
        len(result["people"]) == 1
        and result["people"][0]["verification_status"] == "requires_review"
    )
    assert result["people"][0]["identity_independently_confirmed"] is False


@pytest.mark.asyncio
async def test_later_search_cannot_erase_human_confirmed_identity(db_session):
    service = PeopleDiscoveryService(
        db_session, DiscoveryBudget(get_session_factory()), settings()
    )
    first = await service.search(query())
    contact = await db_session.get(Contact, UUID(first["people"][0]["contact_id"]))
    await service.search(
        query(official_people=[official(human_confirmed=False, role_title="Recruiter")])
    )
    assert contact.role_title == "CTO"
    assert not contact.metadata_["identity_review_required"]
    assert contact.metadata_["identity_human_confirmed"]


@pytest.mark.asyncio
async def test_search_budget_exhaustion_never_executes_provider(db_session):
    from backend.app.schemas.discovery import DiscoveryError, DiscoveryStatus

    class ExhaustedBudget(FakeBudget):
        async def reserve(self, *a):
            raise DiscoveryError(DiscoveryStatus.BUDGET_EXHAUSTED, "Budget exhausted")

    config = settings(
        PEOPLE_SEARCH_ENABLED=True,
        SERPER_API_KEY="fictional",
        PUBLIC_SEARCH_RIGHTS_REVIEWED=True,
        PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL="https://fictional.example/permission",
        LINKEDIN_SEARCH_RETENTION_AUTHORIZED=True,
    )
    result = await PeopleDiscoveryService(db_session, ExhaustedBudget(), config).search(
        PeopleQuery(company_name="Fictional", allow_paid=True)
    )
    assert result["status"] == "budget_exhausted"


@pytest.mark.asyncio
@pytest.mark.parametrize("professional", [True, False])
async def test_retention_preserves_suppression_keys(db_session, professional):
    from backend.app.services.contact_enrichment.retention import prune_provider_data

    evidence = official(
        human_confirmed=False,
        observed_at=now() - timedelta(days=100),
        professional_url="https://fictional.example/team/alex"
        if professional
        else None,
    )
    service = PeopleDiscoveryService(
        db_session, DiscoveryBudget(get_session_factory()), settings()
    )
    first = await service.search(query(official_people=[evidence]))
    contact_id = UUID(first["people"][0]["contact_id"])
    result = await prune_provider_data(db_session, retention_days=90)
    assert result["contacts_pruned"] == 1
    second = await service.search(
        query(official_people=[evidence.model_copy(update={"observed_at": now()})])
    )
    assert second["people"][0]["contact_id"] == str(contact_id)
    assert second["people"][0]["suppressed"]
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 1
