"""Fictional regressions for the public discovery journey; real HTTP is forbidden."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.session import get_session_factory
from backend.app.models.discovery import DiscoveryRun
from backend.app.models.job import Job
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.schemas.discovery import DiscoveryQuery, RunRequest
from backend.app.services.application_assistant import (
    ApplicationAssistant,
    CandidateProfile,
)
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
from backend.app.services.job_discovery_service import JobDiscoveryService, run_output
from backend.app.services.job_sources.direct_api import (
    ArbeitnowAdapter,
    GreenhouseAdapter,
)


def listing(**updates):
    return {
        "slug": "fictional-engineer",
        "title": "Software Engineer",
        "url": "https://www.arbeitnow.com/jobs/fictional-engineer",
        **updates,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_class", [ArbeitnowAdapter, GreenhouseAdapter])
@pytest.mark.parametrize(
    "code,status,attempts",
    [
        (401, "authentication_required", 1),
        (403, "authentication_required", 1),
        (429, "rate_limited", 1),
        (500, "source_unavailable", 2),
    ],
)
async def test_priority_provider_http_failures(adapter_class, code, status, attempts):
    calls = []

    def handler(request):
        assert request.method == "GET" and not request.headers.get("authorization")
        calls.append(request)
        return httpx.Response(
            code, headers={"Retry-After": "23"}, text="private upstream text"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = adapter_class(http_client=client)
        if isinstance(adapter, GreenhouseAdapter):
            adapter.board_token = "fictional"
        result = await adapter.discover(DiscoveryQuery())
    assert result.status == status and not result.jobs and len(calls) == attempts
    assert "private upstream text" not in result.model_dump_json()
    if code == 429:
        assert adapter.retry_after_seconds == 23


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_class", [ArbeitnowAdapter, GreenhouseAdapter])
async def test_priority_provider_timeouts_are_bounded(adapter_class):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = adapter_class(http_client=client)
        if isinstance(adapter, GreenhouseAdapter):
            adapter.board_token = "fictional"
        result = await adapter.discover(DiscoveryQuery())
    assert result.status == "upstream_error" and not result.jobs and len(calls) == 2
    assert "sensitive timeout" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"data": "invalid"}, {"data": [], "links": [1]}, {"data": [None]}]
)
async def test_arbeitnow_malformed_is_not_empty_success(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await ArbeitnowAdapter(client).discover(DiscoveryQuery())
    assert result.status == "upstream_error" and result.errors


@pytest.mark.asyncio
async def test_unknowns_tags_attribution_and_adapter_reuse():
    payloads = [
        {"data": [None]},
        {
            "data": [
                listing(
                    tags=["Senior", "Management"],
                    remote=False,
                    future_field="preserved",
                )
            ]
        },
        {"data": []},
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payloads.pop(0))
        )
    ) as client:
        adapter = ArbeitnowAdapter(client)
        assert (await adapter.discover(DiscoveryQuery())).status == "upstream_error"
        result = await adapter.discover(DiscoveryQuery())
        job = result.jobs[0]
        assert (
            result.status == "success"
            and not result.errors
            and not result.rejected_count
        )
        assert job.skills_required == [] and job.remote_type == "unknown"
        assert (
            job.company_name is None
            and job.location is None
            and job.date_posted is None
        )
        assert job.salary_min is None and "company_unknown" in job.quality_flags
        assert job.data_provenance["source_fields"]["future_field"] == "preserved"
        assert job.data_provenance["source_fields"]["tags"] == ["Senior", "Management"]
        assert job.data_provenance["attribution_url"] == "https://www.arbeitnow.com"
        empty = await adapter.discover(DiscoveryQuery())
        assert (
            empty.status == "no_results"
            and not empty.errors
            and empty.next_cursor is None
        )


@pytest.mark.asyncio
async def test_oversized_decoded_response_is_closed_without_retry(monkeypatch):
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"data":['
            yield b" " * 65

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(ArbeitnowAdapter, "MAX_RESPONSE_BYTES", 64)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Body()))
    ) as client:
        result = await ArbeitnowAdapter(client).discover(DiscoveryQuery())
    assert result.status == "upstream_error" and result.errors == [
        "Provider response exceeds size limit"
    ]
    assert closed == [True]


def test_skill_mentions_do_not_invent_go_c_or_r_experience():
    job = Job(
        id=uuid4(),
        title="Django developer",
        job_url="https://example.com/job",
        source_platform="manual",
        description="Django application using React and C++. <a href='https://go.example'>Details</a>",
        skills_required=[],
    )
    candidate = CandidateProfile(
        full_name="Alex Example",
        email="alex@example.com",
        verified_skills=["Go", "C", "R", "Django", "React", "C++"],
    )
    match = ApplicationAssistant(None).calculate_match(job, candidate)
    assert match.matched_skills == ["Django", "React", "C++"]


@pytest.mark.asyncio
async def test_score_explanation_and_unknowns_agree(phase2_profile):
    job = Job(
        id=uuid4(),
        title="Software Engineer",
        job_url="https://example.com/job",
        source_platform="manual",
        skills_required=[],
    )
    match = JobDiscoveryMatcher(None).match(
        job, CandidateProfileRead.model_validate(phase2_profile)
    )
    assert {
        "company_name",
        "company_size",
        "publication_date",
        "salary",
        "required_skills",
        "location",
        "remote_policy",
    } <= set(match.unknown_fields)
    assert f"{match.match_score:g}/100" in match.explanation
    assert "eligibility review" in match.explanation
    # Facts are observations about a project; they never assert unknown personal skills.
    assert not match.matched_skills


@pytest.mark.asyncio
async def test_expired_run_replay_requires_recovery_and_never_calls_provider(
    db_session,
):
    request = RunRequest(source="arbeitnow", idempotency_key="fictional-crashed-run")
    service = JobDiscoveryService(db_session, get_session_factory())
    run_id, claimed = await service.claim(request)
    assert claimed
    run = await db_session.get(DiscoveryRun, run_id)
    run.started_at = datetime.now(timezone.utc) - timedelta(
        seconds=get_settings().DISCOVERY_TIMEOUT_SECONDS + 121
    )
    await db_session.commit()
    output = await service.run(request)
    assert output["id"] == str(run_id) and output["status"] == "recovery_required"
    assert "no automatic provider replay" in output["errors"][0]
    assert len(list((await db_session.scalars(select(DiscoveryRun))).all())) == 1
    # Rendering is read-only; retain the durable interrupted state for audit.
    assert run.status == "running" and run.finished_at is None
    assert run_output(run)["status"] == "recovery_required"


@pytest.mark.asyncio
async def test_unrestricted_location_and_any_remote_policy_do_not_penalize_known_onsite_jobs(phase2_profile):
    profile = CandidateProfileRead.model_validate(phase2_profile)
    profile = profile.model_copy(update={"preferences": profile.preferences.model_copy(update={"remote_preference": "any", "preferred_locations": []})})
    common = dict(id=uuid4(), title="Software Engineer", job_url="https://example.org/location", source_platform="naukri", skills_required=["Python"], remote_type="onsite", is_remote=False)
    known = JobDiscoveryMatcher(None).match(Job(**common, location="Bengaluru"), profile)
    unknown = JobDiscoveryMatcher(None).match(Job(**common), profile)
    restricted = profile.model_copy(update={"preferences": profile.preferences.model_copy(update={"preferred_locations": ["Delhi"]})})
    mismatch = JobDiscoveryMatcher(None).match(Job(**common, location="Bengaluru"), restricted)
    assert known.match_score == unknown.match_score+20 == mismatch.match_score+20
    assert "Location and remote policy fit preferences" in known.positive_factors
    assert "location" in unknown.unknown_fields
    assert "Location and remote policy fit preferences" not in mismatch.positive_factors
