from uuid import uuid4
import pytest
from sqlalchemy import select

from backend.app.ai.schemas import AnswerGenerationResult
from backend.app.api.v1.application_answers import answer_service
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.models.application_answer import ApplicationAnswerDraft
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.phase2a_fakes import FakeProvider

PRIVATE_PATHS = ["/api/v1/candidate/resources", "/api/v1/candidate/evidence", "/api/v1/application-answers/drafts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PRIVATE_PATHS)
async def test_mandatory_auth(async_client, phase2_auth, path):
    assert (await async_client.get(path)).status_code == 401
    assert (await async_client.get(path, headers={"Authorization": "Bearer wrong"})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PRIVATE_PATHS)
async def test_unconfigured_auth_is_closed(async_client, monkeypatch, path):
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "")
    get_settings.cache_clear()
    assert (await async_client.get(path)).status_code == 503
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_resource_evidence_and_exact_answer_api(async_client, phase2_auth, phase2_profile):
    headers = phase2_auth
    payload = {"resource_type": "resume", "label": "Backend resume", "url": "https://drive.google.com/file/d/fictional/view", "is_primary": True, "user_confirmed": True}
    response = await async_client.post("/api/v1/candidate/resources", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    duplicate = await async_client.post("/api/v1/candidate/resources", headers=headers, json=payload)
    assert duplicate.status_code == 409
    result = await async_client.get("/api/v1/candidate/resources", headers=headers)
    assert result.json()["resources"][0]["label"] == "Backend resume"
    assert any(link["resource_type"] == "github" for link in result.json()["resolved_links"])
    for question, status in [("GitHub profile?", "draft_ready"), ("Resume URL", "draft_ready"), ("Upload resume", "file_upload_required")]:
        result = await async_client.post("/api/v1/candidate/resources/resolve", headers=headers, json={"question": question})
        assert result.json()["status"] == status
    result = await async_client.post("/api/v1/candidate/evidence", headers=headers, json={"evidence_type": "resume_note", "title": "Notes", "content": "I implemented authentication."})
    assert result.status_code == 201 and not result.json()["user_confirmed"]
    eid = result.json()["id"]
    listed = (await async_client.get("/api/v1/candidate/evidence", headers=headers)).json()
    assert len(listed["unverified"]) == 1 and listed["verified"] == []
    assert (await async_client.patch(f"/api/v1/candidate/evidence/{eid}", headers=headers, json={"user_confirmed": True})).json()["user_confirmed"]
    result = await async_client.post("/api/v1/application-answers/generate", headers=headers, json={"question": "Email address"})
    assert result.json()["answer"] == "alex@example.com" and not result.json()["used_llm"]


@pytest.mark.asyncio
async def test_payload_identifiers_and_pagination(async_client, phase2_auth, phase2_profile):
    headers = phase2_auth
    assert (await async_client.post("/api/v1/application-answers/generate", headers=headers, json={"question": "x" * 70000})).status_code == 413
    for payload in [{"question": ""}, {"question": "x" * 2001}, {"question": "q", "max_characters": 0}, {"question": "q", "job_id": "bad"}, {"question": "q", "writing_style": "deceptive"}, {"question": "q", "unexpected": "value"}]:
        assert (await async_client.post("/api/v1/application-answers/generate", headers=headers, json=payload)).status_code == 422
    assert (await async_client.patch("/api/v1/candidate/evidence/bad-id", headers=headers, json={"user_confirmed": True})).status_code == 422
    assert (await async_client.patch(f"/api/v1/candidate/evidence/{uuid4()}", headers=headers, json={"user_confirmed": True})).status_code == 404
    assert (await async_client.get("/api/v1/application-answers/drafts?limit=1000", headers=headers)).status_code == 422
    # Authenticate before validation, even when the input itself is oversized.
    assert (await async_client.post("/api/v1/application-answers/generate", json={"question": "x" * 70000})).status_code == 401


@pytest.mark.asyncio
async def test_no_private_profile_in_public_routes(async_client, phase2_profile, phase2_auth):
    for path in ["/health", "/api/v1/jobs", "/api/v1/credits/status"]:
        response = await async_client.get(path)
        assert "alex@example.com" not in response.text and "Alex Example" not in response.text
    result = await async_client.post(f"/api/v1/candidate/evidence", json={"evidence_type": "other", "title": "test", "content": "private"})
    assert result.status_code == 401 and "private" not in result.text


@pytest.mark.asyncio
async def test_save_list_review_and_stale_api(async_client, db_session, phase2_profile, phase2_auth, phase2_settings):
    fake = FakeProvider()
    service = ApplicationAnswerService(db_session, phase2_settings, fake)
    app.dependency_overrides[answer_service] = lambda: service
    try:
        response = await async_client.post("/api/v1/application-answers/generate", headers=phase2_auth, json={"question": "Describe a project", "save_draft": True})
        assert response.status_code == 200 and response.json()["status"] == "draft_ready", response.text
        await db_session.commit()
        draft_id = response.json()["draft_id"]
        response = await async_client.get("/api/v1/application-answers/drafts?limit=1", headers=phase2_auth)
        assert len(response.json()) == 1 and not response.json()[0]["stale"]
        response = await async_client.patch(f"/api/v1/application-answers/drafts/{draft_id}", headers=phase2_auth, json={"review_status": "reviewed"})
        assert response.json()["review_status"] == "reviewed"
        response = await async_client.patch("/api/v1/profile", headers={**phase2_auth, "If-Match": '"1"'}, json={"summary": "Updated verified summary"})
        assert response.status_code == 200
        response = await async_client.get("/api/v1/application-answers/drafts", headers=phase2_auth)
        assert response.json()[0]["stale"] and response.json()[0]["review_status"] == "reviewed"
    finally:
        app.dependency_overrides.pop(answer_service, None)


@pytest.mark.asyncio
async def test_no_url_fetch_and_no_secrets_in_logs(async_client, phase2_profile, phase2_auth, caplog):
    # Global fixture rejects real network traffic. Saving and resolving a private Drive link is metadata only.
    response = await async_client.post("/api/v1/candidate/resources", headers=phase2_auth, json={"resource_type": "resume", "label": "Private resume", "url": "https://drive.google.com/file/d/private-fictional/view", "user_confirmed": True})
    assert response.status_code == 200
    response = await async_client.post("/api/v1/application-answers/generate", headers=phase2_auth, json={"question": "Describe a project"})
    assert response.json()["error_code"] == "llm_not_configured"
    assert "phase2-fictional-token" not in caplog.text and "alex@example.com" not in caplog.text and "Private resume" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,payload", [
    ("POST", "/api/v1/candidate/resources", {}),
    ("POST", "/api/v1/candidate/resources/resolve", {"question": "GitHub"}),
    ("POST", "/api/v1/candidate/evidence", {}),
    ("PATCH", "/api/v1/candidate/evidence/00000000-0000-0000-0000-000000000000", {"user_confirmed": True}),
    ("POST", "/api/v1/application-answers/generate", {"question": "Email"}),
    ("PATCH", "/api/v1/application-answers/drafts/00000000-0000-0000-0000-000000000000", {"review_status": "reviewed"}),
])
async def test_every_mutation_fails_closed(async_client, monkeypatch, method, path, payload):
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "")
    get_settings.cache_clear()
    assert (await async_client.request(method, path, json=payload)).status_code == 503
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "fictional-token")
    get_settings.cache_clear()
    assert (await async_client.request(method, path, json=payload)).status_code == 401
    assert (await async_client.request(method, path, json=payload, headers={"Authorization": "Bearer invalid"})).status_code == 401
    get_settings.cache_clear()
