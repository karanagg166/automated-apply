import httpx
import pytest
from backend.app.services.job_sources.direct_api import (
    GreenhouseAdapter,
    RemotiveAdapter,
    ArbeitnowAdapter,
    HackerNewsHiringAdapter,
)
from backend.app.schemas.discovery import DiscoveryQuery


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status,attempts",
    [
        (429, "rate_limited", 1),
        (401, "authentication_required", 1),
        (403, "authentication_required", 1),
        (404, "source_unavailable", 1),
        (503, "source_unavailable", 2),
    ],
)
async def test_http_failures_never_look_like_empty_results(code, status, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, text="sensitive provider response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RemotiveAdapter(client).discover(DiscoveryQuery())
    assert result.status == status and result.errors and len(calls) == attempts
    assert "sensitive provider response" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_record_errors_are_isolated_and_reported():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "jobs": [
                        {"title": "No URL"},
                        {
                            "id": 2,
                            "title": "Engineer",
                            "url": "https://remotive.com/jobs/2",
                        },
                    ]
                },
            )
        )
    ) as client:
        result = await RemotiveAdapter(client).discover(DiscoveryQuery())
    assert (
        result.status == "partial"
        and len(result.jobs) == 1
        and result.rejected_count == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"jobs": "invalid"}, {"jobs": [None]}])
async def test_bad_provider_shape(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await RemotiveAdapter(client).discover(DiscoveryQuery())
    assert result.status == "upstream_error" and result.errors


@pytest.mark.asyncio
async def test_arbeitnow_unknown_remote_and_safe_pagination():
    def handler(request):
        assert (
            request.url.host == "www.arbeitnow.com"
            and request.url.params["page"] == "2"
        )
        return httpx.Response(
            200,
            json={
                "links": {"next": "http://169.254.169.254/secret"},
                "data": [
                    {
                        "slug": "a",
                        "title": "Engineer",
                        "url": "https://example.com/jobs/a",
                        "remote": False,
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ArbeitnowAdapter(client).discover(DiscoveryQuery(page=2))
    assert result.status == "success" and result.next_cursor == "3"
    assert (
        result.jobs[0].remote_type == "unknown"
        and result.jobs[0].employment_type is None
    )


@pytest.mark.asyncio
async def test_greenhouse_multiple_configured_boards(monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "GREENHOUSE_BOARDS",
        {"one": "Company One", "two": "Company Two"},
    )

    def handler(request):
        token = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Engineer",
                        "absolute_url": f"https://boards.greenhouse.io/{token}/jobs/1",
                        "updated_at": "2026-10-01T00:00:00Z",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await GreenhouseAdapter(http_client=client).fetch_jobs()
    assert {j.company_name for j in jobs} == {"Company One", "Company Two"}
    assert all(j.date_posted is None and j.company_domain is None for j in jobs)
    with pytest.raises(ValueError):
        await GreenhouseAdapter(board_token="../../secret").fetch_jobs()


@pytest.mark.asyncio
async def test_hn_uses_hiring_thread_not_who_wants_to_be_hired():
    def handler(request):
        if "search_by_date" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"objectID": "1", "title": "Who wants to be hired?"},
                        {"objectID": "2", "title": "Ask HN: Who is hiring?"},
                    ]
                },
            )
        assert request.url.params["numericFilters"] == "parent_id=2"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "3",
                        "parent_id": 2,
                        "comment_text": "Acme | Engineer | Hybrid, London | Full-time<p>Work with us</p>",
                    },
                    {
                        "objectID": "4",
                        "parent_id": 3,
                        "comment_text": "a nested conversation",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HackerNewsHiringAdapter(client).discover(DiscoveryQuery())
    assert result.status == "partial" and len(result.jobs) == 1
    assert (
        result.jobs[0].remote_type == "hybrid"
        and not result.jobs[0].is_confirmed_current
    )


@pytest.mark.asyncio
async def test_greenhouse_pagination_spans_boards_without_losing_jobs(
    monkeypatch, db_session
):
    from backend.app.core.config import get_settings
    from backend.app.services.job_ingestion import JobIngestionService

    monkeypatch.setattr(
        get_settings(), "GREENHOUSE_BOARDS", {"one": "One", "two": "Two"}
    )

    def handler(request):
        board = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": i,
                        "title": "Engineer",
                        "absolute_url": f"https://boards.greenhouse.io/{board}/jobs/{i}",
                    }
                    for i in (1, 2)
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await GreenhouseAdapter(http_client=client).fetch_jobs(page=1, limit=3)
        second = await GreenhouseAdapter(http_client=client).fetch_jobs(page=2, limit=3)
    assert len(first) == 3 and len(second) == 1
    assert len({j.canonical_url for j in first + second}) == 4
    result = await JobIngestionService(db_session).ingest_jobs(first + second)
    assert result.inserted_count == 4 and not result.errors
