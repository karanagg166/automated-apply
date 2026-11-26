"""Draft URL intake never enables, navigates or fills a browser."""

import pytest

URL = "https://job-boards.greenhouse.io/fictional/jobs/123456"
PAYLOAD = {
    "application_url": URL,
    "company_name": "Fictional",
    "job_title": "Engineer",
    "idempotency_key": "fictional-url-intake-01",
}


@pytest.mark.asyncio
async def test_intake_without_browser_permission_is_idempotent_and_remains_unapproved(
    async_client, phase2_auth, phase2_profile
):
    first = await async_client.post(
        "/api/v1/application-packets/intake", json=PAYLOAD, headers=phase2_auth
    )
    assert first.status_code == 201, first.text
    packet = first.json()
    again = await async_client.post(
        "/api/v1/application-packets/intake", json=PAYLOAD, headers=phase2_auth
    )
    assert again.status_code == 201 and again.json()["id"] == packet["id"]
    assert packet["approved_revision"] is None
    assert packet["tracking_state"] == "not_applied"
    assert packet["snapshot"]["destination"]["source_confidence"] == "unverified"
    # The legacy browser-assistant route was retired in Phase 9E.
    assert (
        await async_client.post(
            "/api/v1/browser-applications", json=PAYLOAD, headers=phase2_auth
        )
    ).status_code == 404
    changed = {**PAYLOAD, "company_name": "Wrong employer"}
    assert (
        await async_client.post(
            "/api/v1/application-packets/intake", json=changed, headers=phase2_auth
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_url_intake_owner_boundary_and_rejected_destinations(
    async_client, phase2_auth
):
    path = "/api/v1/application-packets/intake"
    assert (await async_client.post(path, json=PAYLOAD)).status_code == 401
    assert (
        await async_client.post(
            path, json=PAYLOAD, headers={**phase2_auth, "X-Agent-Client": "extension"}
        )
    ).status_code == 403
    for url in [
        "http://127.0.0.1/jobs/1",
        "https://jobs.lever.co.attacker.example/company/job",
        "https://www.linkedin.com/jobs/view/123",
        "https://jobs.lever.co/login",
        "https://job-boards.greenhouse.io/company/jobs/123?redirect=https://evil.example",
    ]:
        response = await async_client.post(
            path, json={**PAYLOAD, "application_url": url}, headers=phase2_auth
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_intake_requires_actual_posting_metadata(async_client, phase2_auth):
    for field in ("company_name", "job_title"):
        response = await async_client.post("/api/v1/application-packets/intake", headers=phase2_auth, json={**PAYLOAD, field: "  "})
        assert response.status_code == 422
