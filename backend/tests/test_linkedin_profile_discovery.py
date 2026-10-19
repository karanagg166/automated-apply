import httpx
import pytest
from backend.app.services.people_discovery.base import PeopleQuery, PublicPerson
from backend.app.services.people_discovery.normalizer import (
    normalize_linkedin_url,
    mark_ambiguities,
)
from backend.app.services.people_discovery.public_search import PublicSearchAdapter
from backend.app.services.people_discovery.service import PeopleDiscoveryService
from backend.tests.discovery_fakes import settings, FakeBudget


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com/in/person?trk=email",
        "https://in.linkedin.com/in/person/",
        "https://www.linkedin.com/in/person#details",
    ],
)
def test_profile_url_normalization(url):
    assert normalize_linkedin_url(url) == "https://www.linkedin.com/in/person/"


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com.evil.com/in/person",
        "https://www.linkedin.com/jobs/view/1",
        "https://www.linkedin.com/in/person/details",
        "https://127.0.0.1/in/person",
        "https://linkedin.com/company/example",
    ],
)
def test_restricted_or_non_profile_urls(url):
    with pytest.raises(ValueError):
        normalize_linkedin_url(url)


def test_company_url_supported_explicitly():
    assert (
        normalize_linkedin_url(
            "https://linkedin.com/company/example?trk=x", allow_company=True
        )
        == "https://www.linkedin.com/company/example/"
    )


@pytest.mark.asyncio
async def test_search_calls_only_search_provider_and_preserves_role_evidence(
    db_session,
):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "google.serper.dev" and request.method == "POST"
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Alex Example - CTO at Acme - LinkedIn",
                        "link": "https://linkedin.com/in/alex?trk=search",
                        "snippet": "CTO at Acme",
                    },
                    {
                        "title": "Alex Example - CTO at Acme - LinkedIn",
                        "link": "https://linkedin.com/in/alex/",
                        "snippet": "CTO at Acme",
                    },
                    {
                        "title": "Sam Example - Acme - LinkedIn",
                        "link": "https://linkedin.com/in/sam/",
                        "snippet": "Acme professional",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PeopleDiscoveryService(
            db_session,
            FakeBudget(),
            settings(PEOPLE_SEARCH_ENABLED=True, SERPER_API_KEY="fictional-key"),
            PublicSearchAdapter("fictional-key", client),
        ).search(PeopleQuery(company_name="Acme", roles=["cto"], allow_paid=True))
    assert len(requests) == 1 and len(result["people"]) == 2
    assert result["people"][0]["role"] == "cto"
    assert (
        result["people"][1]["role"] is None
        and result["people"][1]["verification_status"] == "requires_review"
    )
    assert all(p["outreach_mode"] == "manual" for p in result["people"])


def test_ambiguous_name_never_silently_selects_one():
    people = [
        PublicPerson(
            name="Alex Example",
            linkedin_url=f"https://linkedin.com/in/alex-{n}",
            evidence_url="https://example.com/team",
            verification_status="source_reported",
        )
        for n in (1, 2)
    ]
    assert all(
        p.verification_status == "requires_review" for p in mark_ambiguities(people)
    )


@pytest.mark.asyncio
async def test_search_rate_limit_sanitizes_errors(db_session):
    budget = FakeBudget()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, text="secret"))
    ) as client:
        result = await PeopleDiscoveryService(
            db_session,
            budget,
            settings(PEOPLE_SEARCH_ENABLED=True, SERPER_API_KEY="secret"),
            PublicSearchAdapter("secret", client),
        ).search(PeopleQuery(company_name="Acme", allow_paid=True))
    assert result["status"] == "rate_limited" and budget.cooled
    assert "secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,status",
    [
        (
            PeopleQuery(company_name="Acme", source="linkedin"),
            "authentication_required",
        ),
        (PeopleQuery(company_name="Acme"), "configuration_required"),
    ],
)
async def test_restricted_sources_report_honestly(db_session, query, status):
    result = await PeopleDiscoveryService(db_session, FakeBudget(), settings()).search(
        query
    )
    assert result["status"] == status and result["people"] == []
