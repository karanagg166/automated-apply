import httpx
import pytest
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
from backend.app.schemas.discovery import DiscoveryQuery
from backend.tests.discovery_fakes import settings, actor_config, FakeBudget


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source", ["naukri", "instahyre", "wellfound", "work_at_a_startup"]
)
async def test_source_actor_input_and_provenance(source):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            import json

            assert json.loads(request.content) == {
                "searchTerms": "Python",
                "cities": ["India"],
                "maximum": 2,
            }
            assert request.url.params["maxTotalChargeUsd"] == "0.1"
            assert request.url.params["timeout"] == "60"
            assert source in str(request.url)
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "r1",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "d1",
                        "usageTotalUsd": 0.02,
                    }
                },
            )
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "one",
                    "url": f"https://{source}.example.com/jobs/one",
                    "title": "Engineer",
                    "companyName": "Example",
                }
            ],
        )

    budget = FakeBudget()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ApifyJobAdapter(
            source_name=source,
            configuration=actor_config(actor_id=f"fictional/{source}"),
            settings=settings(),
            http_client=client,
            budget=budget,
        )
        result = await adapter.discover(
            DiscoveryQuery(keywords=["Python"], locations=["India"], limit=2),
            allow_paid=True,
        )
    assert result.status == "success" and result.jobs[0].source_name == source
    assert result.jobs[0].data_provenance["portal"] == source
    assert result.jobs[0].data_provenance["actor_id"] == f"fictional/{source}"
    assert len(calls) == 2 and len(budget.calls) == 1
    assert result.usage["billing_final"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["QUEUED", "READY", "RUNNING", "FAILED", "ABORTED", "TIMED-OUT"]
)
async def test_incomplete_or_failed_run_never_fetches_dataset(state):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert "/datasets/" not in str(request.url)
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={"data": {"id": "r1", "status": state, "defaultDatasetId": "d1"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ApifyJobAdapter(
            source_name="instahyre",
            configuration=actor_config(),
            settings=settings(),
            http_client=client,
            budget=FakeBudget(),
        )
        result = await adapter.discover(DiscoveryQuery(), allow_paid=True)
    assert result.status == "upstream_error" and result.jobs == []
    assert len(calls) <= 5


@pytest.mark.asyncio
async def test_run_poll_success_and_invalid_record_quarantine():
    statuses = iter(["RUNNING", "SUCCEEDED"])

    def handler(request):
        if "/datasets/" in str(request.url):
            return httpx.Response(
                200,
                json=[
                    {"title": "Fiction without URL"},
                    {"title": "Engineer", "url": "https://example.com/job/1"},
                ],
            )
        state = next(statuses)
        return httpx.Response(
            200, json={"data": {"id": "r1", "status": state, "defaultDatasetId": "d1"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ApifyJobAdapter(
            source_name="naukri",
            configuration=actor_config(),
            settings=settings(),
            http_client=client,
            budget=FakeBudget(),
        ).discover(DiscoveryQuery(limit=2), allow_paid=True)
    assert (
        result.status == "partial"
        and len(result.jobs) == 1
        and result.rejected_count == 1
    )
    assert result.jobs[0].company_name is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"api_token": ""}, "missing_credentials"),
        ({"configuration": actor_config(enabled=False)}, "configuration_required"),
        ({"configuration": {}}, "configuration_required"),
        ({"budget": None}, "authentication_required"),
    ],
)
async def test_configuration_and_approval_are_required(kwargs, status):
    options = dict(
        source_name="naukri",
        configuration=actor_config(),
        settings=settings(),
        budget=FakeBudget(),
    )
    options.update(kwargs)
    result = await ApifyJobAdapter(**options).discover(
        DiscoveryQuery(), allow_paid=True
    )
    assert result.status == status


@pytest.mark.asyncio
async def test_paid_approval_and_platform_override_cannot_be_bypassed():
    adapter = ApifyJobAdapter(
        source_name="instahyre",
        configuration=actor_config(),
        settings=settings(),
        budget=FakeBudget(),
    )
    assert (
        await adapter.discover(DiscoveryQuery())
    ).status == "authentication_required"
    assert (
        await adapter.discover(DiscoveryQuery(), portal="naukri", allow_paid=True)
    ).status == "unsupported_operation"
    with pytest.raises(PermissionError):
        await adapter.fetch_jobs(portal="linkedin")


@pytest.mark.asyncio
async def test_rate_limit_has_cooldown_and_no_retry():
    budget = FakeBudget()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, text="fictional-token must never be exposed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ApifyJobAdapter(
            source_name="naukri",
            configuration=actor_config(),
            settings=settings(),
            http_client=client,
            budget=budget,
        ).discover(DiscoveryQuery(), allow_paid=True)
    assert result.status == "rate_limited" and len(calls) == 1 and budget.cooled
    assert "fictional-token" not in result.model_dump_json()
