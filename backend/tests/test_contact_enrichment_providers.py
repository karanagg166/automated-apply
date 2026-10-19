import json
import uuid

import httpx
import pytest

from backend.app.services.contact_enrichment.provider_factory import get_provider
from backend.app.services.contact_enrichment.schemas import (
    ContactEnrichmentRequest,
    State,
)
from backend.tests.contact_enrichment_fakes import (
    URL,
    apollo_response,
    settings,
    signal_response,
)


def query(**kwargs):
    return ContactEnrichmentRequest(
        **{
            **dict(
                company_id=uuid.uuid4(),
                full_name="Alex Fictional",
                company_domain="fictional.example.com",
                linkedin_url=URL,
                allow_paid=True,
            ),
            **kwargs,
        }
    )


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_normalized_email_is_provider_reported_and_private_fields_dropped(name):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200, json=apollo_response() if name == "apollo" else signal_response()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status == State.COMPLETED
    assert result.contacts[0].email_status == "provider_reported"
    assert result.contacts[0].provider_verification_claim in {"verified", "rating:100"}
    assert "private@gmail.com" not in result.model_dump_json()
    assert "+1999999999" not in result.model_dump_json()
    request = seen[0]
    assert (
        request.headers["x-api-key" if name == "apollo" else "apikey"]
        == "fictional-" + name + "-key"
    )
    body = json.loads(request.content)
    if name == "apollo":
        assert (
            body["reveal_personal_emails"] is False
            and body["run_waterfall_email"] is False
        )
    else:
        assert body == {"items": [URL], "withoutWaterfall": True}


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
@pytest.mark.parametrize(
    "code,expected",
    [
        (401, "authorization_required"),
        (403, "authorization_required"),
        (404, "not_found"),
        (422, "failed"),
        (429, "rate_limited"),
        (500, "failed"),
        (503, "failed"),
        (402, "budget_exhausted"),
        (302, "failed"),
    ],
)
async def test_http_errors_are_sanitized_no_retries(name, code, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            code,
            headers={"Retry-After": "120", "Location": "http://127.0.0.1/"},
            text="secret-key raw-private-provider-response",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status == expected and len(calls) == 1
    assert "secret-key" not in result.model_dump_json()
    if code == 429:
        assert result.retry_after_seconds == 120


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
@pytest.mark.parametrize(
    "payload", [None, {}, "bad", 17, {"person": []}, [{"status": "success"}]]
)
async def test_malformed_response(name, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status in {State.FAILED, State.NOT_FOUND}


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_timeout_is_uncertain_not_retried(name):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("contains fictional-key", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status == State.UNCERTAIN and len(calls) == 1
    assert "fictional-key" not in result.model_dump_json()


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
@pytest.mark.parametrize(
    "overrides,expected",
    [({"allow_paid": False}, "authorization_required"), ({}, "not_configured")],
)
async def test_configuration_and_authorization_fail_without_http(
    name, overrides, expected
):
    configured = (
        settings() if overrides else settings(APOLLO_API_KEY="", SIGNALHIRE_API_KEY="")
    )
    result = await get_provider(name, configured).enrich_person(query(**overrides))
    assert result.status == expected


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_disabled_provider(name):
    configured = settings(
        APOLLO_ENRICHMENT_ENABLED=False, SIGNALHIRE_ENRICHMENT_ENABLED=False
    )
    assert (
        await get_provider(name, configured).enrich_person(query())
    ).status == State.NOT_CONFIGURED


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_wrong_company_is_not_a_contact(name):
    payload = (
        apollo_response(organization={"primary_domain": "wrong.example.com"})
        if name == "apollo"
        else signal_response(
            experience=[{"current": True, "website": "https://wrong.example.com"}]
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status == State.NOT_FOUND and result.contacts == []


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_missing_optional_email_and_linkedin(name):
    payload = (
        apollo_response(email=None, linkedin_url=None)
        if name == "apollo"
        else signal_response(contacts=[], social=[])
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await get_provider(name, settings(), client).enrich_person(query())
    assert result.status == State.COMPLETED
    assert result.contacts[0].email is None and result.contacts[0].linkedin_url is None
    assert result.contacts[0].email_status == "unknown"


async def test_signalhire_unexpected_async_is_queued():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(201, json={"requestId": "fictional-async-id"})
        )
    ) as client:
        result = await get_provider("signalhire", settings(), client).enrich_person(
            query()
        )
    assert result.status == State.QUEUED and not result.contacts


@pytest.mark.parametrize(
    "status,expected",
    [
        ("failed", "not_found"),
        ("credits_are_over", "budget_exhausted"),
        ("duplicate_query", "running"),
    ],
)
async def test_signalhire_item_states(status, expected):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=[{"item": URL, "status": status}])
        )
    ) as client:
        result = await get_provider("signalhire", settings(), client).enrich_person(
            query()
        )
    assert result.status == expected


async def test_signalhire_balance_and_safe_connection():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"credits": 27})
        )
    ) as client:
        provider = get_provider("signalhire", settings(), client)
        assert (await provider.get_usage()).credits_remaining == 27
        assert (await provider.test_connection()).status == State.COMPLETED


async def test_apollo_health_usage_and_bounded_deduplicated_search():
    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"is_logged_in": True, "healthy": True})
        body = json.loads(request.content)
        assert body["page"] == 1 and body["per_page"] == 5
        return httpx.Response(200, json={"people": [apollo_response()["person"]] * 5})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = get_provider("apollo", settings(), client)
        assert (await provider.test_connection()).status == State.COMPLETED
        assert (await provider.get_usage()).status == State.UNSUPPORTED
        result = await provider.search_people(query())
    assert len(result.contacts) == 1 and result.credits_used == 0


async def test_unsupported_and_unknown_provider():
    assert (
        await get_provider("signalhire", settings()).search_people(query())
    ).status == State.UNSUPPORTED
    assert (
        await get_provider("signalhire", settings()).enrich_person(
            query(linkedin_url=None)
        )
    ).status == State.UNSUPPORTED
    with pytest.raises(ValueError):
        get_provider("fake", settings())


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/admin",
        "https://linkedin.com.evil.com/in/alex",
        "https://www.linkedin.com/company/example",
        "http://localhost",
        "https://user:password@linkedin.com/in/alex",
    ],
)
def test_arbitrary_urls_rejected(url):
    with pytest.raises(ValueError):
        query(linkedin_url=url)


@pytest.mark.parametrize("name", ["apollo", "signalhire"])
async def test_response_size_bounded(name):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * 1048577)
        )
    ) as client:
        assert (
            await get_provider(name, settings(), client).enrich_person(query())
        ).status == State.FAILED


async def test_signalhire_no_content_means_running():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(204))
    ) as client:
        result = await get_provider("signalhire", settings(), client).enrich_person(
            query()
        )
    assert result.status == State.RUNNING and not result.contacts
