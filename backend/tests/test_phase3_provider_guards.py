"""Provider metadata fixtures; no live call, personal account or paid operation."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.app.schemas.discovery import DiscoveryError, DiscoveryQuery
from backend.app.services.contact_enrichment.apollo_capabilities import (
    ENDPOINTS,
    credit_balance,
    endpoint_limits,
    preflight,
)
from backend.app.services.contact_enrichment.base import ProviderError
from backend.app.services.contact_enrichment.providers.apollo import ApolloProvider
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
from backend.app.services.providers.apify import (
    INVESTIGATED_ACTORS,
    ApifyRoutePool,
    OfficialApifyAPI,
)
from backend.tests.discovery_fakes import FakeBudget, actor_config, settings


@pytest.mark.parametrize("actor", INVESTIGATED_ACTORS)
async def test_apify_linkedin_metadata_is_get_only_and_execution_stays_blocked(actor):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and "Authorization" not in request.headers
        if request.url.path.endswith("openapi.json"):
            return httpx.Response(
                200,
                json={
                    "paths": {
                        "/run": {
                            "post": {
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "limit": {"type": "integer"}
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "title": "Provider metadata",
                    "pricingInfos": [
                        {
                            "pricingModel": "PAY_PER_EVENT",
                            "revision": "observed-not-permanent",
                        }
                    ],
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        metadata = await OfficialApifyAPI(client=client).actor(actor)
        assert (
            metadata.collection_status == "disabled_pending_review"
            and metadata.schema_digest
        )
        budget = FakeBudget()
        adapter = ApifyJobAdapter(
            source_name="naukri",
            configuration=actor_config(actor_id=actor),
            settings=settings(),
            budget=budget,
            http_client=client,
        )
        result = await adapter.discover(DiscoveryQuery(), allow_paid=True)
        assert (
            result.status == "configuration_required"
            and len(calls) == 2
            and not budget.calls
        )


@pytest.mark.parametrize(
    "inputs",
    [
        {"cookies": []},
        {"sessionCookie": "private"},
        {"startUrls": ["https://linkedin.com/company/example"]},
        {"chromeProfile": "profile"},
    ],
)
async def test_apify_personal_credentials_and_linkedin_inputs_never_dispatch(inputs):
    budget = FakeBudget()
    result = await ApifyJobAdapter(
        source_name="naukri",
        configuration=actor_config(fixed_input=inputs),
        settings=settings(),
        budget=budget,
    ).discover(DiscoveryQuery(), allow_paid=True)
    assert result.status == "configuration_required" and not budget.calls


async def test_apify_unapproved_run_dataset_and_actor_paths_are_blocked_before_http():
    api = OfficialApifyAPI(token="fictional")
    for operation in (
        api.actor("../../users/me"),
        api.run_status("other-run"),
        api.dataset("other-dataset"),
    ):
        with pytest.raises(DiscoveryError):
            await operation


async def test_apify_metadata_does_not_follow_external_schema_refs():
    def respond(request):
        return httpx.Response(
            200,
            json={"data": {"title": "Fixture"}}
            if not request.url.path.endswith("json")
            else {
                "paths": {
                    "/run": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "http://127.0.0.1/private"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert (
            await OfficialApifyAPI(client=client).actor("fictional/actor")
        ).input_schema is None


async def test_apify_route_pool_never_rotates_account_or_replays_ambiguous_dispatch():
    budget = FakeBudget()
    first = ApifyJobAdapter(
        source_name="naukri",
        settings=settings(),
        configuration=actor_config(),
        budget=budget,
    )
    second = ApifyJobAdapter(
        source_name="naukri",
        settings=settings(),
        configuration=actor_config(),
        budget=budget,
    )
    with pytest.raises(ValueError, match="one credential"):
        ApifyRoutePool(
            [
                first,
                ApifyJobAdapter(
                    source_name="naukri",
                    settings=settings(),
                    api_token="different",
                    budget=budget,
                ),
            ]
        )
    calls = []

    async def ambiguous(*args, **kwargs):
        calls.append("first")
        raise TimeoutError("Dispatch outcome unknown")

    first.discover = ambiguous
    pool = ApifyRoutePool([first, second])
    with pytest.raises(TimeoutError):
        await pool.discover(DiscoveryQuery(), allow_paid=True)
    assert calls == ["first"]


def apollo_settings(**values):
    return SimpleNamespace(
        **{
            "APOLLO_FREE_ACCOUNT_CONFIRMED": True,
            "APOLLO_WORK_EMAIL_CONFIRMED": True,
            "APOLLO_ELIGIBILITY_REVIEWED_AT": datetime.now(timezone.utc),
            "APOLLO_ELIGIBILITY_EVIDENCE_URL": "https://example.com/owner-reviewed-eligibility",
            "APOLLO_REVIEWED_ENDPOINTS": list(ENDPOINTS.values()),
            "APOLLO_CREDIT_POOL": "credits",
            **values,
        }
    )


def usage(left=10):
    return {"limit": 10, "consumed": 10 - left, "left_over": left}


async def test_apollo_preflight_reads_actual_free_endpoint_allowance_and_credit_pool():
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("health"):
            return httpx.Response(200, json={"is_logged_in": True, "healthy": True})
        if request.url.path.endswith("credit_usage_stats"):
            return httpx.Response(200, json={"credits": usage(5)})
        return httpx.Response(
            200,
            json={
                ENDPOINTS["enrich_person"]: {
                    p: usage(8) for p in ("minute", "hour", "day")
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await preflight(
            ApolloProvider("fictional", True, client),
            apollo_settings(),
            "enrich_person",
            1,
        )
    assert result["credits"]["remaining"] == 5 and result["eligibility_verified"]
    assert len(calls) == 3 and not any(
        r.url.path.endswith("/people/match") for r in calls
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"APOLLO_FREE_ACCOUNT_CONFIRMED": False},
        {"APOLLO_WORK_EMAIL_CONFIRMED": False},
        {"APOLLO_REVIEWED_ENDPOINTS": []},
        {
            "APOLLO_ELIGIBILITY_REVIEWED_AT": datetime.now(timezone.utc)
            - timedelta(days=2)
        },
    ],
)
async def test_apollo_unreviewed_or_premium_account_never_reaches_http(changes):
    with pytest.raises(ProviderError, match="eligibility"):
        await preflight(
            ApolloProvider("fictional", True),
            apollo_settings(**changes),
            "enrich_person",
            1,
        )


@pytest.mark.parametrize(
    "credit,rate,expected", [(0, 8, "budget_exhausted"), (5, 0, "rate_limited")]
)
async def test_apollo_hard_stops_before_enrichment(credit, rate, expected):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("health"):
            return httpx.Response(200, json={"is_logged_in": True, "healthy": True})
        if request.url.path.endswith("credit_usage_stats"):
            return httpx.Response(200, json={"credits": usage(credit)})
        return httpx.Response(
            200,
            json={
                ENDPOINTS["enrich_person"]: {
                    p: usage(rate) for p in ("minute", "hour", "day")
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderError) as exc:
            await preflight(
                ApolloProvider("fictional", True, client),
                apollo_settings(),
                "enrich_person",
                1,
            )
        assert exc.value.state == expected
    assert len(calls) == 3


@pytest.mark.parametrize("value", [True, -1, "5", float("nan"), float("inf")])
def test_apollo_invalid_credit_values_do_not_authorize(value):
    with pytest.raises(ValueError):
        credit_balance(
            {"credits": {"limit": 10, "consumed": 0, "left_over": value}}, "credits"
        )
    with pytest.raises(ValueError):
        endpoint_limits({}, ENDPOINTS["enrich_person"])
