"""No MCP sending boundary, sender spoofing, accidental authorization or secret logging."""

import uuid

import pytest

from backend.app.mcp.permissions import TOOL_CAPABILITIES, allowed_capabilities
from backend.app.mcp.registry import mcp
from backend.tests.phase4b_fakes import request_from


@pytest.mark.asyncio
async def test_no_mcp_send_tool_or_capability():
    tools = await mcp.list_tools()
    assert not any("send" in tool.name for tool in tools)
    assert "send_email" not in allowed_capabilities()
    assert "send_email" not in TOOL_CAPABILITIES.values()


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


@pytest.mark.asyncio
async def test_no_secret_or_body_logs(sending_bundle, caplog):
    service, draft, _, *_ = sending_bundle
    preview = await service.preview(draft["id"])
    result = await service.send(draft["id"], request_from(preview))
    for private in (
        "fictional-access",
        "fictional-refresh",
        preview["confirmation_token"],
        draft["body"],
    ):
        assert private not in caplog.text
        if private != draft["body"]:
            assert private not in str(result)
