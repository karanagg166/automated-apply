"""Official ATS schemas against fictional feeds; external HTTP is forbidden."""

from copy import deepcopy

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.schemas.discovery import DiscoveryError, DiscoveryQuery, RunRequest
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.app.services.job_sources.registry import source_registry
from backend.app.services.startup_discovery.connectivity import (
    configuration_fingerprint,
)

ADAPTERS = [LeverAdapter, AshbyAdapter]


def configuration(**updates):
    return Settings(
        _env_file=None,
        LEVER_BOARDS={"fictional": "Fictional Employer"},
        ASHBY_BOARDS={"fictional": "Fictional Employer"},
        **updates,
    )


def posting(adapter, **updates):
    if adapter is LeverAdapter:
        return {
            "id": "fictional-post-001",
            "text": "Python Engineer",
            "hostedUrl": "https://jobs.lever.co/fictional/fictional-post-001",
            "applyUrl": "https://jobs.lever.co/fictional/fictional-post-001/apply",
            "descriptionPlain": "Build APIs using Python.",
            "categories": {"location": "Bengaluru", "commitment": "Full-time"},
            "workplaceType": "hybrid",
            "createdAt": 1700000000000,
            "salaryRange": {
                "currency": "INR",
                "interval": "per-year-salary",
                "min": 900000,
                "max": 1500000,
            },
            **updates,
        }
    return {
        "title": "Python Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/fictional/fictional-post-001",
        "applyUrl": "https://jobs.ashbyhq.com/fictional/fictional-post-001/application",
        "descriptionPlain": "Build APIs using Python.",
        "isListed": True,
        "location": "Bengaluru",
        "isRemote": True,
        "workplaceType": "Hybrid",
        "employmentType": "FullTime",
        "publishedAt": "2026-01-02T10:00:00Z",
        "compensation": {
            "scrapeableCompensationSalarySummary": "INR 900000 - 1500000",
            "summaryComponents": [
                {"compensationType": "EquityPercentage", "minValue": 1, "maxValue": 2},
                {
                    "compensationType": "Salary",
                    "currencyCode": "INR",
                    "interval": "1 YEAR",
                    "minValue": 900000,
                    "maxValue": 1500000,
                },
            ],
        },
        **updates,
    }


def feed(adapter, records):
    return records if adapter is LeverAdapter else {"apiVersion": "1", "jobs": records}


async def discover(adapter, payload, query=None, settings=None):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and not request.headers.get("authorization")
        assert request.url.host in {
            "api.lever.co",
            "api.eu.lever.co",
            "api.ashbyhq.com",
        }
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(
            http_client=client, settings=settings or configuration()
        ).discover(query or DiscoveryQuery())
    return result, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_valid_public_postings(adapter):
    result, calls = await discover(adapter, feed(adapter, [posting(adapter)]))
    assert result.status == "success" and len(calls) == 1
    job = result.jobs[0]
    assert job.company_name == "Fictional Employer" and job.title == "Python Engineer"
    assert (
        job.location == "Bengaluru"
        and job.remote_type == "hybrid"
        and job.is_remote is None
    )
    assert job.salary_min == 900000 and job.salary_max == 1500000
    assert job.salary_currency == "INR" and job.salary_period == "year"
    assert job.employment_type == "full_time" and not job.skills_required
    assert job.canonical_url == job.original_url and not job.canonical_url.endswith(
        ("apply", "application")
    )
    assert bool(job.date_posted) == (adapter is AshbyAdapter)
    assert job.data_provenance["company_name_basis"] == "operator_configured_board"
    assert result.usage["public_feed"]["http_attempts"] == 1
    assert result.usage["public_feed"]["decoded_bytes"] > 0
    assert result.usage["public_feed"]["json_seconds"] >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "code,status,attempts",
    [
        (401, "authentication_required", 1),
        (403, "authentication_required", 1),
        (404, "source_unavailable", 1),
        (429, "rate_limited", 1),
        (500, "source_unavailable", 2),
        (302, "source_unavailable", 1),
    ],
)
async def test_http_errors_and_redirects(adapter, code, status, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            code,
            headers={"Location": "http://127.0.0.1/private", "Retry-After": "23"},
            text="private provider error",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        obj = adapter(client, configuration())
        result = await obj.discover(DiscoveryQuery())
    assert result.status == status and not result.jobs and len(calls) == attempts
    assert "private provider error" not in result.model_dump_json()
    if code == 429:
        assert obj.retry_after_seconds == 23


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_timeouts_size_limit_and_invalid_json(adapter, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, configuration()).discover(DiscoveryQuery())
    assert result.status == "upstream_error" and len(calls) == 2
    monkeypatch.setattr(adapter, "MAX_RESPONSE_BYTES", 64)
    for body in (b" " * 65, b"{invalid json"):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
        ) as client:
            result = await adapter(client, configuration()).discover(DiscoveryQuery())
        assert result.status == "upstream_error" and not result.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "payload", [None, "bad", 1, {}, {"jobs": "bad"}, {"jobs": [], "apiVersion": "2"}]
)
async def test_malformed_top_level_is_not_empty_success(adapter, payload):
    result, _ = await discover(adapter, payload)
    assert result.status == "upstream_error" and not result.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("record", [None, [], {}, {"title": ""}, {"id": True}])
async def test_malformed_records_are_reported_as_partial(adapter, record):
    result, _ = await discover(adapter, feed(adapter, [posting(adapter), record]))
    assert (
        result.status == "partial"
        and len(result.jobs) == 1
        and result.rejected_count == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_exact_and_inconsistent_duplicates(adapter):
    good = posting(adapter)
    result, _ = await discover(adapter, feed(adapter, [good, deepcopy(good)]))
    assert result.status == "success" and len(result.jobs) == 1
    different = {
        **good,
        ("text" if adapter is LeverAdapter else "title"): "Other Engineer",
    }
    result, _ = await discover(adapter, feed(adapter, [good, different]))
    assert (
        result.status == "partial"
        and len(result.jobs) == 1
        and result.rejected_count == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/jobs",
        "https://169.254.169.254/latest",
        "https://jobs.lever.co.evil.example/fictional/x",
        "https://jobs.ashbyhq.com@evil.example/x",
        "https://jobs.ashbyhq.com/other/post",
        "https://jobs.lever.co:443/fictional/x",
        "https://evil.example/redirect",
    ],
)
async def test_untrusted_posting_urls_are_never_fetched(adapter, url):
    record = posting(
        adapter, **{("hostedUrl" if adapter is LeverAdapter else "jobUrl"): url}
    )
    result, calls = await discover(adapter, feed(adapter, [record]))
    assert (
        result.status == "upstream_error"
        and result.rejected_count == 1
        and len(calls) == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_identity_and_application_url_conflicts(adapter):
    record = posting(
        adapter,
        applyUrl=f"https://{adapter(None, configuration()).job_host}/fictional/different-post/application",
    )
    result, _ = await discover(adapter, feed(adapter, [record]))
    assert result.status == "upstream_error"
    if adapter is LeverAdapter:
        result, _ = await discover(adapter, [posting(adapter, id="different-post")])
        assert result.status == "upstream_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_missing_optional_fields_remain_unknown(adapter):
    record = posting(adapter)
    for key in (
        "categories",
        "location",
        "workplaceType",
        "isRemote",
        "publishedAt",
        "compensation",
        "salaryRange",
        "salaryDescriptionPlain",
        "employmentType",
        "applyUrl",
        "descriptionPlain",
    ):
        record.pop(key, None)
    result, _ = await discover(adapter, feed(adapter, [record]))
    job = result.jobs[0]
    assert result.status == "success" and job.remote_type == "unknown"
    assert job.date_posted is None and job.salary_min is None and job.location is None


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "bad",
    [
        {"min": True},
        {"min": -1},
        {"min": "100"},
        {"min": 2e12},
        {"min": 2000000},
        {"currency": "$"},
        {"interval": "unknown"},
    ],
)
async def test_invalid_salary_never_becomes_asserted_pay(adapter, bad):
    record = posting(adapter)
    if adapter is LeverAdapter:
        record["salaryRange"].update(bad)
    else:
        names = {
            "min": "minValue",
            "max": "maxValue",
            "currency": "currencyCode",
            "interval": "interval",
        }
        record["compensation"]["summaryComponents"][1].update(
            {names[k]: v for k, v in bad.items()}
        )
    result, _ = await discover(adapter, feed(adapter, [record]))
    assert (
        result.status == "success"
        and result.jobs[0].salary_min is None
        and result.jobs[0].salary_max is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interval,period",
    [
        ("per-year-salary", "year"),
        ("per-month-salary", "month"),
        ("per-week-salary", "week"),
        ("per-day-wage", "day"),
        ("per-hour-wage", "hour"),
        ("bi-week-salary", None),
        ("one-time", None),
    ],
)
async def test_lever_documented_salary_intervals(interval, period):
    record = posting(LeverAdapter)
    record["salaryRange"]["interval"] = interval
    result, _ = await discover(LeverAdapter, [record])
    assert result.status == "success" and result.jobs[0].salary_period == period
    assert (result.jobs[0].salary_min is not None) == (period is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "workplace,flag,remote",
    [
        ("Remote", True, "remote"),
        ("Hybrid", True, "hybrid"),
        ("OnSite", False, "onsite"),
        (None, True, "unknown"),
        (None, False, "unknown"),
        ("Future", True, "unknown"),
    ],
)
async def test_ashby_remote_semantics(workplace, flag, remote):
    result, _ = await discover(
        AshbyAdapter,
        feed(
            AshbyAdapter,
            [posting(AshbyAdapter, workplaceType=workplace, isRemote=flag)],
        ),
    )
    assert result.status == "success" and result.jobs[0].remote_type == remote


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"publishedAt": "bad"},
        {"publishedAt": "2099-01-01T00:00:00Z"},
        {"workplaceType": "Hybrid", "isRemote": False},
        {"isRemote": "true"},
        {"isListed": None},
    ],
)
async def test_ashby_inconsistent_evidence(updates):
    result, _ = await discover(
        AshbyAdapter, feed(AshbyAdapter, [posting(AshbyAdapter, **updates)])
    )
    assert result.status == "upstream_error" and not result.jobs


@pytest.mark.asyncio
async def test_unlisted_is_excluded_and_equity_is_not_salary():
    record = posting(AshbyAdapter)
    record["compensation"]["summaryComponents"] = [
        {"compensationType": "EquityPercentage", "minValue": 1, "maxValue": 2}
    ]
    result, _ = await discover(
        AshbyAdapter,
        feed(AshbyAdapter, [posting(AshbyAdapter, isListed=False), record]),
    )
    assert len(result.jobs) == 1 and result.jobs[0].salary_min is None
    result, _ = await discover(
        AshbyAdapter, feed(AshbyAdapter, [posting(AshbyAdapter, isListed=False)])
    )
    assert result.status == "no_results" and not result.jobs


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    "board",
    [
        "https://evil.example",
        "../private",
        "a/b",
        "a?url=evil",
        "a%2fb",
        "localhost:80",
        "",
        "x" * 101,
    ],
)
def test_board_configuration_rejects_urls_and_path_injection(adapter, board):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            **{adapter.source_name.upper() + "_BOARDS": {board: "Fictional"}},
        )


@pytest.mark.parametrize(
    "boards",
    [
        {"test": ""},
        {"test": " "},
        {"test": "x" * 256},
        {"test": "A", "Test": "B"},
        {str(i): "A" for i in range(11)},
    ],
)
def test_invalid_employer_allowlists(boards):
    with pytest.raises(ValueError):
        Settings(_env_file=None, ASHBY_BOARDS=boards)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_unconfigured_never_performs_http(adapter):
    def deny(request):
        pytest.fail("Unconfigured provider called HTTP")

    settings = Settings(_env_file=None)
    config = source_registry(settings)[adapter.source_name]
    assert config.availability == "configuration_required"
    assert config.read_only and config.pricing == "free" and not config.live_verified
    assert config.configuration["board_allowlist_required"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(deny)) as client:
        obj = JobSourceFactory.get_adapter(
            adapter.source_name, settings=settings, http_client=client
        )
        result = await obj.discover(DiscoveryQuery())
        assert result.status == "configuration_required" and not result.jobs
        assert (await obj.test_connection())["status"] == "not_attempted"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_runtime_urls_board_overrides_and_redirect_hosts_are_rejected(adapter):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("Unexpected HTTP"))
    ) as client:
        obj = adapter(client, configuration())
        with pytest.raises(DiscoveryError):
            await obj.request(client, "https://evil.example/jobs")
        with pytest.raises(DiscoveryError):
            await obj.fetch_jobs(board_token="other")
    with pytest.raises(ValueError):
        RunRequest(source=adapter.source_name, query={"url": "https://evil.example"})


@pytest.mark.asyncio
async def test_lever_eu_host_and_identity_namespace():
    record = posting(LeverAdapter)
    record["hostedUrl"] = record["hostedUrl"].replace(
        "jobs.lever.co", "jobs.eu.lever.co"
    )
    record["applyUrl"] = record["applyUrl"].replace("jobs.lever.co", "jobs.eu.lever.co")
    result, calls = await discover(
        LeverAdapter, [record], settings=configuration(LEVER_REGION="eu")
    )
    assert result.status == "success" and calls[0].url.host == "api.eu.lever.co"
    assert result.jobs[0].data_provenance["board_token"] == "eu:fictional"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_empty_feed_and_local_pagination(adapter):
    result, _ = await discover(adapter, feed(adapter, []))
    assert result.status == "no_results"
    records = []
    for i in range(3):
        record = posting(adapter)
        for key in ("id", "hostedUrl", "applyUrl", "jobUrl"):
            if key in record:
                record[key] = record[key].replace(
                    "fictional-post-001", f"fictional-post-00{i}"
                )
        records.append(record)
    result, _ = await discover(
        adapter, feed(adapter, records), DiscoveryQuery(limit=1, page=2)
    )
    assert len(result.jobs) == 1 and result.next_cursor == "3"
    assert result.jobs[0].source_job_id == "fictional-post-001"


def test_connectivity_fingerprint_tracks_boards_and_region():
    settings = configuration()
    for provider in ("lever", "ashby"):
        changed = settings.model_copy(
            update={provider.upper() + "_BOARDS": {"other": "Other"}}
        )
        assert configuration_fingerprint(
            provider, settings
        ) != configuration_fingerprint(provider, changed)
    assert configuration_fingerprint("lever", settings) != configuration_fingerprint(
        "lever", configuration(LEVER_REGION="eu")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_multiple_allowlisted_boards_namespace_identical_ids(adapter):
    settings = Settings(
        _env_file=None,
        **{
            adapter.source_name.upper() + "_BOARDS": {
                "first": "First Employer",
                "second": "Second Employer",
            }
        },
    )
    calls = []

    def handler(request):
        calls.append(request)
        board = request.url.path.split("/")[-1]
        record = posting(adapter)
        for key in ("hostedUrl", "jobUrl", "applyUrl"):
            if key in record:
                record[key] = record[key].replace("/fictional/", f"/{board}/")
        return httpx.Response(200, json=feed(adapter, [record]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, settings).discover(DiscoveryQuery(limit=2))
    assert result.status == "success" and len(result.jobs) == 2 and len(calls) == 2
    assert {j.company_name for j in result.jobs} == {
        "First Employer",
        "Second Employer",
    }
    assert result.jobs[0].source_job_id == result.jobs[1].source_job_id
    assert (
        result.jobs[0].data_provenance["board_token"]
        != result.jobs[1].data_provenance["board_token"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_later_board_failure_never_reports_first_board_as_complete(adapter):
    settings = Settings(
        _env_file=None,
        **{
            adapter.source_name.upper() + "_BOARDS": {
                "fictional": "Fictional",
                "second": "Second",
            }
        },
    )

    def handler(request):
        if request.url.path.endswith("/second"):
            return httpx.Response(500)
        return httpx.Response(200, json=feed(adapter, [posting(adapter)]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, settings).discover(DiscoveryQuery(limit=2))
    assert result.status == "source_unavailable" and not result.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_reusing_adapter_resets_error_and_request_evidence(adapter):
    payloads = [
        feed(adapter, [None]),
        feed(adapter, [posting(adapter)]),
        feed(adapter, []),
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payloads.pop(0))
        )
    ) as client:
        obj = adapter(client, configuration())
        assert (await obj.discover(DiscoveryQuery())).status == "upstream_error"
        result = await obj.discover(DiscoveryQuery())
        assert (
            result.status == "success"
            and not result.errors
            and not result.rejected_count
        )
        assert result.usage["public_feed"]["http_attempts"] == 1
        result = await obj.discover(DiscoveryQuery())
        assert result.status == "no_results" and not result.next_cursor
