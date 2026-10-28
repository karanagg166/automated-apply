"""Fictional public feeds; no provider credentials or live vacancies."""


import httpx
import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.core.job_urls import ats_job_url
from backend.app.schemas.discovery import DiscoveryQuery
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.registry import source_registry
from backend.app.services.job_sources.smartrecruiters import SmartRecruitersAdapter
from backend.app.services.startup_discovery.connectivity import (
    configuration_fingerprint,
)


def config(**updates):
    return Settings(_env_file=None, SMARTRECRUITERS_BOARDS={"Fictional": "Fictional Labs"}, **updates)


def posting(identifier="12345678", **updates):
    record = dict(
        id=identifier, name="Junior Python Engineer", active=True,
        company={"identifier": "Fictional", "name": "Fictional Labs"},
        postingUrl=f"https://jobs.smartrecruiters.com/Fictional/{identifier}-junior-python",
        applyUrl=f"https://jobs.smartrecruiters.com/Fictional/{identifier}-junior-python?oga=true",
        releasedDate="2026-10-27T12:00:00Z",
        location={"city": "Bengaluru", "country": "in", "remote": True},
        experienceLevel={"label": "Entry Level"},
        typeOfEmployment={"label": "Full-time"},
        jobAd={"sections": {"jobDescription": {"text": "Build Python services."}}},
    )
    record.update(updates)
    return record


def fixture_handler(records, calls, *, total=None):
    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.smartrecruiters.com"
        assert "authorization" not in request.headers
        if request.url.path.endswith("/postings"):
            offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
            return httpx.Response(200, json={
                "offset": offset, "limit": limit, "totalFound": len(records) if total is None else total,
                "content": [{"id": x["id"], "ref": "https://untrusted.example/private"} for x in records[offset:offset + limit]],
            })
        identifier = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=next(x for x in records if x["id"] == identifier))
    return respond


async def test_documented_public_feed_pagination_normalization_and_no_ref_fetch():
    calls, records = [], [posting(str(12345678 + n)) for n in range(3)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_handler(records, calls))) as client:
        adapter = SmartRecruitersAdapter(client, config())
        result = await adapter.discover(DiscoveryQuery(limit=2))
        assert result.status == "success" and result.next_cursor == "2"
        item = result.jobs[0]
        assert item.country == "in" and item.remote_type == "remote"
        assert item.experience_level == "Entry Level" and item.employment_type == "full_time"
        assert item.date_posted.isoformat() == "2026-10-27T12:00:00+00:00"
        assert item.company_intelligence == {} and not item.skills_required
        assert item.canonical_url == "https://jobs.smartrecruiters.com/Fictional/12345678"
        second = await adapter.discover(DiscoveryQuery(limit=2, page=2))
        assert len(second.jobs) == 1 and second.next_cursor is None
        assert len(calls) == 5
        assert all("untrusted" not in str(r.url) for r in calls)
        assert adapter.metrics["http_attempts"] == 2


@pytest.mark.parametrize("code,expected", [(403, "authentication_required"), (429, "rate_limited"), (503, "source_unavailable")])
async def test_permission_rate_and_upstream_failures_are_explicit(code, expected):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(code, headers={"Retry-After": "60"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = SmartRecruitersAdapter(client, config())
        result = await adapter.discover(DiscoveryQuery())
        assert result.status == expected and not result.jobs
        assert len(calls) == (2 if code == 503 else 1)


async def test_timeout_is_bounded_and_does_not_dispatch_mutations():
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("fictional timeout")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await SmartRecruitersAdapter(client, config()).discover(DiscoveryQuery())
        assert result.status == "upstream_error" and not result.jobs
        assert len(calls) == 2 and all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("change", [
    {"active": False}, {"id": "different"},
    {"company": {"identifier": "Other"}},
    {"postingUrl": "https://jobs.smartrecruiters.com/Other/12345678-role"},
    {"applyUrl": "https://jobs.smartrecruiters.com/Fictional/99999999-role"},
    {"postingUrl": "https://jobs.smartrecruiters.com@untrusted.example/Fictional/12345678-role"},
    {"releasedDate": "not-a-date"},
])
async def test_inconsistent_or_inactive_postings_do_not_become_vacancies(change):
    record = posting(**change)
    # List identity is independent of tampered detail identity.
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"offset": 0, "limit": 20, "totalFound": 1, "content": [{"id": "12345678"}]})
        return httpx.Response(200, json=record)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await SmartRecruitersAdapter(client, config()).discover(DiscoveryQuery())
        assert result.status == "upstream_error" and result.rejected_count == 1
        assert not result.jobs


async def test_malformed_pagination_and_redirect_never_follow_unreviewed_paths():
    for response in [httpx.Response(302, headers={"Location": "https://untrusted.example/"}),
                     httpx.Response(200, json={"totalFound": True, "content": [], "offset": 0, "limit": 20})]:
        calls = []
        def respond(request):
            calls.append(request)
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await SmartRecruitersAdapter(client, config()).discover(DiscoveryQuery())
            assert not result.jobs and len(calls) == 1


def test_sources_configuration_and_manual_only_disclosure():
    settings = config()
    registry = source_registry(settings)
    assert registry["smartrecruiters"].availability == "available"
    assert isinstance(JobSourceFactory.get_adapter("smartrecruiters", settings=settings), SmartRecruitersAdapter)
    assert source_registry(Settings(_env_file=None))["smartrecruiters"].availability == "configuration_required"
    for source in ["simplify", "workday", "company_careers"]:
        assert registry[source].availability == "manual_import_only"
        assert registry[source].operations == ["manual_import"]
    other = settings.model_copy(update={"SMARTRECRUITERS_BOARDS": {"Other": "Other Labs"}})
    assert configuration_fingerprint("smartrecruiters", settings) != configuration_fingerprint("smartrecruiters", other)
    for boards in [{"../private": "Fictional"}, {"Fictional": ""}, {"A": "A", "a": "A"}]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, SMARTRECRUITERS_BOARDS=boards)


def test_smartrecruiters_and_eu_lever_application_identity():
    item = posting()
    assert ats_job_url(item["postingUrl"]) == ats_job_url(item["applyUrl"])
    assert ats_job_url("https://jobs.eu.lever.co/fictional/fictional-post-001/apply") == "https://jobs.eu.lever.co/fictional/fictional-post-001"
    assert ats_job_url("https://jobs.smartrecruiters.com/Other/12345678-role") != ats_job_url(item["postingUrl"])
