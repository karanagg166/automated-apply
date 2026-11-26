import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.models.discovery import DiscoveryRun
from backend.app.models.job import Job
from backend.tests.discovery_fakes import job


@pytest.fixture
def headers(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "JOB_AGENT_API_TOKEN", SecretStr("test-discovery-token")
    )
    return {"Authorization": "Bearer test-discovery-token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/discovery/sources"),
        ("POST", "/api/v1/discovery/preview"),
        ("POST", "/api/v1/discovery/runs"),
        ("PUT", "/api/v1/discovery/runs/" + str(uuid.uuid4())),
        ("GET", "/api/v1/discovery/runs/" + str(uuid.uuid4())),
        ("GET", "/api/v1/jobs/search"),
        ("POST", "/api/v1/discovery/people/search"),
        ("GET", "/api/v1/companies/" + str(uuid.uuid4()) + "/people"),
        ("GET", "/api/v1/jobs"),
    ],
)
async def test_all_discovery_endpoints_authenticate_before_validation(
    async_client, headers, method, path
):
    for authentication in ({}, {"Authorization": "Bearer wrong"}):
        response = await async_client.request(
            method, path, headers=authentication, content=b"invalid json"
        )
        assert (
            response.status_code == 401
            and response.headers["Cache-Control"] == "no-store"
        )


@pytest.mark.asyncio
async def test_preview_no_network_no_writes_no_secrets(
    async_client, headers, db_session, monkeypatch
):
    monkeypatch.setattr(get_settings(), "APIFY_API_TOKEN", "must-never-leak")
    response = await async_client.post(
        "/api/v1/discovery/preview",
        headers=headers,
        json={"source": "instahyre", "allow_paid": True},
    )
    assert response.status_code == 200 and response.json()["provider_calls"] == 0
    assert (
        "must-never-leak" not in response.text
        and "must-never-leak"
        not in (
            await async_client.get("/api/v1/discovery/sources", headers=headers)
        ).text
    )
    assert await db_session.scalar(select(func.count()).select_from(DiscoveryRun)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_owner_discovery_uuid_replays_only_the_original_scope(async_client, headers):
    run_id = uuid.uuid4()
    path = f"/api/v1/discovery/runs/{run_id}"
    payload = {"source": "manual", "use_profile": False}
    assert (
        await async_client.put(f"{path}?dispatch=true", headers=headers, json=payload)
    ).status_code == 400
    assert (await async_client.get(path, headers=headers)).status_code == 404

    response = await async_client.put(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    outcome = response.json()
    assert outcome["id"] == str(run_id)
    assert outcome["local_intake_complete"] and outcome["rankings_complete"]
    replay = await async_client.put(path, headers=headers, json=payload)
    assert replay.json() == outcome
    assert (await async_client.get(path, headers=headers)).json() == outcome
    changed = await async_client.put(
        path, headers=headers, json={**payload, "use_profile": True}
    )
    assert changed.status_code == 409


@pytest.mark.asyncio
async def test_manual_import_run_idempotency_search_and_people(async_client, headers):
    payload = {
        "source": "internshala",
        "idempotency_key": "import_one",
        "query": {"limit": 2},
        "manual_jobs": [
            job(source_name="internshala").model_dump(mode="json"),
            {"title": "Invalid record"},
        ],
    }
    response = await async_client.post(
        "/api/v1/discovery/runs", headers=headers, json=payload
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert (
        result["status"] == "partial"
        and result["counts"]["inserted"] == 1
        and result["counts"]["rejected"] == 1
    )
    repeated = await async_client.post(
        "/api/v1/discovery/runs", headers=headers, json=payload
    )
    assert repeated.json() == result
    payload["query"]["limit"] = 3
    assert (
        await async_client.post("/api/v1/discovery/runs", headers=headers, json=payload)
    ).status_code == 409
    read = await async_client.get(
        "/api/v1/discovery/runs/" + result["id"], headers=headers
    )
    assert read.json() == result
    jobs = await async_client.get(
        "/api/v1/jobs/search?platform=internshala&remote_type=remote&limit=1",
        headers=headers,
    )
    assert jobs.status_code == 200 and jobs.json()["total"] == 1
    stored = jobs.json()["jobs"][0]
    assert (
        stored["source_verification_status"] == "requires_review"
        and stored["match"] is None
    )
    assert stored["company_domain"] == "example.com"
    assert stored["source_observations"][0]["source"] == "internshala"
    assert stored["source_observations"][0]["provenance"]["import_mode"] == "manual"
    company_id = stored["company_id"]
    people = await async_client.post(
        "/api/v1/discovery/people/search",
        headers=headers,
        json={
            "company_name": "Example",
            "company_domain": "example.com",
            "source": "manual",
            "manual_people": [
                {
                    "name": "Alex Example",
                    "role": "CTO",
                    "linkedin_url": "https://linkedin.com/in/example-person",
                    "evidence_url": "https://example.com/team",
                }
            ],
        },
    )
    assert (
        people.status_code == 200
        and people.json()["people"][0]["outreach_mode"] == "manual"
    )
    evidence = await async_client.get(
        f"/api/v1/companies/{company_id}/people", headers=headers
    )
    assert evidence.status_code == 200 and len(evidence.json()["people"]) == 1


@pytest.mark.asyncio
async def test_profile_ranking_exclusions_and_minimum_score(
    async_client, headers, phase2_profile
):
    response = await async_client.post(
        "/api/v1/discovery/runs",
        headers=headers,
        json={"source": "manual", "manual_jobs": [job().model_dump(mode="json")]},
    )
    assert response.status_code == 200
    assert response.json()["rankings"][0]["matched_skills"] == ["Python"]
    result = await async_client.get(
        "/api/v1/jobs/search?rank=true&sort=match&minimum_match_score=0",
        headers=headers,
    )
    assert result.json()["total"] == 1 and result.json()["jobs"][0]["match"][
        "missing_skills"
    ] == ["Go"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"source": "missing"},
        {"source": "manual", "query": {"limit": 101}},
        {"source": "manual", "query": {"page": 0}},
        {"source": "manual", "query": {"keywords": ["a" * 201]}},
        {"source": "naukri", "manual_jobs": [{}]},
    ],
)
async def test_invalid_and_oversized_inputs(async_client, headers, payload):
    response = await async_client.post(
        "/api/v1/discovery/runs", headers=headers, json=payload
    )
    assert response.status_code in (400, 422)
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_body_limit_and_ssrf_attempts(async_client, headers):
    oversized = await async_client.post(
        "/api/v1/discovery/runs", headers=headers, content=b"x" * 1048577
    )
    assert oversized.status_code == 413
    payload = {
        "source": "manual",
        "manual_jobs": [
            job().model_dump(mode="json")
            | {"original_url": "https://169.254.169.254/meta"}
        ],
    }
    response = await async_client.post(
        "/api/v1/discovery/runs", headers=headers, json=payload
    )
    assert (
        response.json()["counts"]["rejected"] == 1
        and response.json()["counts"]["inserted"] == 0
    )
    people = await async_client.post(
        "/api/v1/discovery/people/search",
        headers=headers,
        json={"company_name": "Example", "company_domain": "127.0.0.1"},
    )
    assert people.status_code == 422


@pytest.mark.asyncio
async def test_paid_disabled_run_is_recorded_without_network(async_client, headers):
    result = await async_client.post(
        "/api/v1/discovery/runs",
        headers=headers,
        json={"source": "naukri", "allow_paid": True},
    )
    assert (
        result.status_code == 200 and result.json()["status"] == "missing_credentials"
    )
    assert result.json()["counts"]["inserted"] == 0 and result.json()["finished_at"]
