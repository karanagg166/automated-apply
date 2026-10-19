"""Protected REST preview, explicit confirmation, sanitized status and pagination."""

import uuid

import pytest

from backend.app.api.v1.outreach import sending_service
from backend.app.main import app
from backend.tests.phase4b_fakes import request_from


@pytest.mark.asyncio
async def test_owner_send_flow_api(sending_bundle, async_client, phase2_auth):
    service, draft, client, *_ = sending_bundle
    app.dependency_overrides[sending_service] = lambda: service
    try:
        path = f"/api/v1/outreach/drafts/{draft['id']}"
        preview = await async_client.post(path + "/send-preview", headers=phase2_auth)
        assert preview.status_code == 200, preview.text
        assert preview.headers["cache-control"] == "no-store" and not client.calls
        request = request_from(preview.json()).model_dump(mode="json")
        result = await async_client.post(
            path + "/send", json=request, headers=phase2_auth
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["status"] == "accepted_by_gmail"
        assert (
            "fictional-access" not in result.text
            and "confirmation_token" not in result.text
        )
        status = await async_client.get(
            "/api/v1/outreach/send-attempts/" + body["id"], headers=phase2_auth
        )
        assert (
            status.status_code == 200 and status.json()["status"] == "accepted_by_gmail"
        )
        history = await async_client.get(
            "/api/v1/outreach/history?limit=1&offset=0", headers=phase2_auth
        )
        assert history.status_code == 200 and history.json()["total"] == 1
        assert len(client.calls) == 1
        assert (
            await async_client.get(
                "/api/v1/outreach/history?limit=0", headers=phase2_auth
            )
        ).status_code == 422
        assert (
            await async_client.get(
                f"/api/v1/outreach/send-attempts/{uuid.uuid4()}", headers=phase2_auth
            )
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(sending_service)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "boolean_only",
        "missing_token",
        "bad_hash",
        "bad_revision",
        "bad_sender",
        "bad_key",
    ],
)
async def test_request_validation_no_secrets(
    sending_bundle, async_client, phase2_auth, change
):
    service, draft, client, *_ = sending_bundle
    preview = await service.preview(draft["id"])
    data = request_from(preview).model_dump(mode="json")
    if change == "extra":
        data["from"] = "spoof@example.com"
    elif change == "boolean_only":
        data = {"confirmed": True}
    elif change == "missing_token":
        del data["confirmation_token"]
    else:
        field, value = {
            "bad_hash": ("approval_hash", "private-invalid"),
            "bad_revision": ("expected_revision", True),
            "bad_sender": ("sender_account_id", "private-invalid"),
            "bad_key": ("idempotency_key", "private invalid"),
        }[change]
        data[field] = value
    response = await async_client.post(
        f"/api/v1/outreach/drafts/{draft['id']}/send", json=data, headers=phase2_auth
    )
    assert (
        response.status_code == 422
        and "private" not in response.text
        and not client.calls
    )


@pytest.mark.asyncio
async def test_send_blockers_are_structured(sending_bundle, async_client, phase2_auth):
    service, draft, client, contact, *_ = sending_bundle
    contact.do_not_contact = True
    await service.session.commit()
    app.dependency_overrides[sending_service] = lambda: service
    try:
        response = await async_client.post(
            f"/api/v1/outreach/drafts/{draft['id']}/send-preview", headers=phase2_auth
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "send_blocked"
        assert "contact_suppressed" in response.json()["detail"]["blockers"]
        assert not client.calls
    finally:
        app.dependency_overrides.pop(sending_service)
