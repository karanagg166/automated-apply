"""Gmail sending was removed from the HTTP API (read + draft only, 2026-11-26).

The previous end-to-end send-flow tests exercised routes that no longer exist.
These tests pin the removal: every former send endpoint is unreachable even
for an authenticated owner, and drafts remain readable.
"""

import uuid

import pytest

DRAFT = "/api/v1/outreach/drafts/" + str(uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", [
    ("post", DRAFT + "/send-preview", None),
    ("post", DRAFT + "/send", {"confirmation_token": "x" * 32}),
    ("get", "/api/v1/outreach/send-attempts/" + str(uuid.uuid4()), None),
    ("get", "/api/v1/outreach/history", None),
])
async def test_former_send_endpoints_are_gone(async_client, phase2_auth, method, path, body):
    kwargs = {"headers": phase2_auth}
    if body is not None:
        kwargs["json"] = body
    response = await getattr(async_client, method)(path, **kwargs)
    assert response.status_code in {404, 405}, response.text


@pytest.mark.asyncio
async def test_draft_listing_still_available(async_client, phase2_auth):
    response = await async_client.get("/api/v1/outreach/drafts", headers=phase2_auth)
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"drafts", "limit", "offset", "total"}
