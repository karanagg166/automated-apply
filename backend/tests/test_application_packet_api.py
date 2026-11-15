"""Protected REST workflow, redacted validation, transaction rollback and concurrency."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.models.application_packet import ApplicationEvent, ApplicationPacket
from backend.app.schemas.applications import ApplicationEventRead

pytestmark = pytest.mark.asyncio

ROOT = "/api/v1/application-packets"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/applications/platforms"),
        ("GET", ROOT),
        ("GET", ROOT + "/bad"),
        ("POST", "/api/v1/jobs/bad/application-preview"),
        ("POST", "/api/v1/jobs/bad/application-packets"),
        ("PATCH", ROOT + "/bad"),
        ("POST", ROOT + "/bad/questions"),
        ("POST", ROOT + "/bad/questions/bad/generate"),
        ("PATCH", ROOT + "/bad/questions/bad"),
        ("GET", ROOT + "/bad/readiness"),
        ("POST", ROOT + "/bad/review"),
        ("GET", ROOT + "/bad/handoff"),
        ("POST", ROOT + "/bad/report-submission"),
        ("PATCH", ROOT + "/bad/tracking"),
        ("GET", ROOT + "/bad/events"),
    ],
)
async def test_authentication_precedes_payload_and_path_validation(
    async_client, phase2_auth, method, path
):
    for headers in [{}, {"Authorization": "Bearer wrong-token"}]:
        response = await async_client.request(
            method, path, headers=headers, content=b"{malformed private body"
        )
        assert (
            response.status_code == 401
            and response.headers["cache-control"] == "no-store"
        )


async def test_fail_closed_unconfigured_auth(async_client, monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "")
    get_settings.cache_clear()
    response = await async_client.get("/api/v1/applications/platforms")
    assert (
        response.status_code == 503 and response.headers["cache-control"] == "no-store"
    )


async def test_complete_rest_workflow(async_client, phase2_auth, application_target):
    job, _ = application_target

    async def call(method, path, **kwargs):
        response = await async_client.request(
            method, path, headers=phase2_auth, **kwargs
        )
        assert response.status_code in {200, 201}, response.text
        assert response.headers["cache-control"] == "no-store"
        return response.json()

    capability = await call("GET", "/api/v1/applications/platforms")
    assert capability[0]["live_verified"] is False
    preview = await call("POST", f"/api/v1/jobs/{job.id}/application-preview", json={})
    assert preview["submission_mode"] == "manual_handoff"
    packet = await call(
        "POST",
        f"/api/v1/jobs/{job.id}/application-packets",
        json={"idempotency_key": "rest-fictional-001"},
    )
    pid = packet["id"]
    packet = await call(
        "POST",
        f"{ROOT}/{pid}/questions",
        json={
            "expected_revision": 1,
            "questions": [{"question": "Describe a backend service you built"}],
        },
    )
    field = packet["fields"][-1]
    packet = await call(
        "PATCH",
        f"{ROOT}/{pid}/questions/{field['id']}",
        json={
            "expected_revision": packet["revision"],
            "answer": "I implemented backend authentication using Python and FastAPI.",
        },
    )
    packet = await call(
        "POST",
        f"{ROOT}/{pid}/review",
        json={
            "expected_revision": packet["revision"],
            "action": "approve",
            "reviewed_field_ids": [field["id"]],
            "confirm_resume": True,
            "confirm_destination": True,
        },
    )
    handoff = await call("GET", f"{ROOT}/{pid}/handoff")
    assert handoff["fields"][-1]["effective_answer"].startswith("I implemented")
    assert not handoff["submitted"]
    packet = await call(
        "PATCH",
        f"{ROOT}/{pid}/tracking",
        json={
            "expected_revision": packet["revision"],
            "lifecycle_state": "external_application_opened",
        },
    )
    evidence = await call(
        "POST",
        f"{ROOT}/{pid}/report-submission",
        json={
            "expected_revision": packet["revision"],
            "idempotency_key": "rest-submitted-001",
            "human_confirmed": True,
            "confirmation": "I submitted this application on the official website",
        },
    )
    assert evidence["confirmation_source"] == "user_reported"
    readiness = await call("GET", f"{ROOT}/{pid}/readiness")
    assert readiness["state"] == "completed_by_user"
    events = await call("GET", f"{ROOT}/{pid}/events")
    assert events[-1]["event_type"] == "user_reported_submission"
    listed = await call(
        "GET", ROOT + "?platform=naukri&status=user_reported_submitted&limit=1"
    )
    assert len(listed["packets"]) == 1


async def test_existing_worker_history_is_readable_without_accepting_arbitrary_origins(
    async_client, phase2_auth, application_target, db_session
):
    job, _ = application_target
    created = await async_client.post(
        f"/api/v1/jobs/{job.id}/application-packets",
        headers=phase2_auth,
        json={"idempotency_key": "fictional-worker-history"},
    )
    assert created.status_code == 201
    packet = created.json()
    for origin in ("system", "local_worker"):
        db_session.add(ApplicationEvent(
            packet_id=UUID(packet["id"]), event_type="profile_checked",
            previous_state="created", next_state="created", packet_revision=1,
            origin=origin,
        ))
    await db_session.commit()
    response = await async_client.get(f"{ROOT}/{packet['id']}/events", headers=phase2_auth)
    assert response.status_code == 200
    events = response.json()
    assert {event["origin"] for event in events} == {"owner_rest", "system", "local_worker"}
    with pytest.raises(ValidationError):
        ApplicationEventRead.model_validate({**events[-1], "origin": "untrusted_website"})


async def test_concurrent_revision_is_conflict_and_errors_do_not_mutate(
    async_client, phase2_auth, application_target, db_session
):
    job, _ = application_target
    response = await async_client.post(
        f"/api/v1/jobs/{job.id}/application-packets",
        headers=phase2_auth,
        json={"idempotency_key": "rest-conflict-001"},
    )
    packet = response.json()
    pid = packet["id"]
    payload = {"expected_revision": 1, "answer": "Alex Fictional"}
    url = f"{ROOT}/{pid}/questions/{packet['fields'][0]['id']}"
    assert (
        await async_client.patch(url, headers=phase2_auth, json=payload)
    ).status_code == 200
    assert (
        await async_client.patch(url, headers=phase2_auth, json=payload)
    ).status_code == 409
    before = await db_session.scalar(select(func.count()).select_from(ApplicationEvent))
    response = await async_client.post(
        f"{ROOT}/{pid}/review",
        headers=phase2_auth,
        json={
            "expected_revision": 2,
            "action": "approve",
            "confirm_resume": True,
            "confirm_destination": True,
        },
    )
    assert response.status_code == 409
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationEvent))
        == before
    )
    response = await async_client.get(f"{ROOT}/{pid}", headers=phase2_auth)
    assert response.json()["revision"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        {
            "idempotency_key": "bad-metadata",
            "snapshot": {"secret": "private-invalid-value"},
        },
        {
            "idempotency_key": "bad-metadata",
            "questions": [
                {"question": "private-invalid-value", "field_type": "yes_no"}
            ],
        },
        {
            "idempotency_key": "bad-metadata",
            "candidate_profile_id": "private-invalid-value",
        },
    ],
)
async def test_untrusted_metadata_rejected_and_sanitized(
    async_client, phase2_auth, application_target, payload
):
    response = await async_client.post(
        f"/api/v1/jobs/{application_target[0].id}/application-packets",
        headers=phase2_auth,
        json=payload,
    )
    assert response.status_code == 422 and "private-invalid-value" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_size_limit_and_cross_object_questions(
    async_client, phase2_auth, application_target
):
    response = await async_client.post(
        "/api/v1/applications/platforms", headers=phase2_auth, content=b"x" * 65537
    )
    assert (
        response.status_code == 413 and response.headers["cache-control"] == "no-store"
    )
    job, _ = application_target
    response = await async_client.post(
        f"/api/v1/jobs/{job.id}/application-packets",
        headers=phase2_auth,
        json={"idempotency_key": "cross-object-001"},
    )
    packet = response.json()
    response = await async_client.patch(
        f"{ROOT}/{packet['id']}/questions/{uuid4()}",
        headers=phase2_auth,
        json={"expected_revision": 1, "answer": "Example"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"human_confirmed": False},
        {"human_confirmed": "true"},
        {"human_confirmed": 1},
        {"provider_receipt": "fake"},
        {"confirmation_source": "provider_confirmed"},
        {"confirmation": "Opened the URL"},
    ],
)
async def test_no_fake_submission_input(
    async_client, phase2_auth, application_target, override
):
    response = await async_client.post(
        f"/api/v1/jobs/{application_target[0].id}/application-packets",
        headers=phase2_auth,
        json={"idempotency_key": "no-fake-submit-001"},
    )
    packet = response.json()
    response = await async_client.post(
        f"{ROOT}/{packet['id']}/report-submission",
        headers=phase2_auth,
        json={
            "expected_revision": 1,
            "idempotency_key": "no-fake-report-001",
            "human_confirmed": True,
            "confirmation": "I submitted this application on the official website",
            **override,
        },
    )
    assert response.status_code == 422


async def test_storage_exception_rolls_back_and_is_redacted(
    async_client, phase2_auth, application_target, monkeypatch, db_session
):
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.repositories.application_packet import ApplicationPacketRepository

    async def fail_after_flush(self, packet_id):
        raise SQLAlchemyError("private-secret-database-password")

    monkeypatch.setattr(ApplicationPacketRepository, "fields", fail_after_flush)
    response = await async_client.post(
        f"/api/v1/jobs/{application_target[0].id}/application-packets",
        headers=phase2_auth,
        json={"idempotency_key": "rest-rollback-001"},
    )
    assert response.status_code == 503 and "private-secret" not in response.text
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationPacket))
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 0
    )
