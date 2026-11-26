"""No MCP sending boundary, sender spoofing, accidental authorization or secret logging."""

import importlib.util
import uuid

import pytest

from backend.app.main import app


def test_no_mcp_send_tool_or_capability():
    # The legacy FastMCP HTTP server (and its tool registry) was retired in Phase 9E;
    # it must stay gone and nothing may be mounted at /mcp again.
    assert importlib.util.find_spec("backend.app.mcp") is None
    assert not any(getattr(route, "path", "").startswith("/mcp") for route in app.routes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer invalid", "Bearer fictional-mcp-owner-token-at-least-32-characters"],
)
async def test_all_send_routes_require_owner_bearer(
    async_client, phase2_auth, authorization
):
    headers = {"Authorization": authorization} if authorization else {}
    for method, path in [
        ("POST", f"/api/v1/outreach/drafts/{uuid.uuid4()}/send-preview"),
        ("POST", f"/api/v1/outreach/drafts/{uuid.uuid4()}/send"),
        ("GET", f"/api/v1/outreach/send-attempts/{uuid.uuid4()}"),
        ("GET", "/api/v1/outreach/history"),
    ]:
        response = await async_client.request(method, path, headers=headers)
        assert (
            response.status_code == 401
            and response.headers["cache-control"] == "no-store"
        )


@pytest.mark.asyncio
async def test_conflicting_bearers_are_rejected(async_client, phase2_auth):
    response = await async_client.post(
        f"/api/v1/outreach/drafts/{uuid.uuid4()}/send-preview",
        headers=[
            ("Authorization", phase2_auth["Authorization"]),
            ("Authorization", "Bearer other"),
        ],
    )
    assert response.status_code == 401

