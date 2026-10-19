"""Read-only application tools share the service and never confer approval/send authority."""

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from backend.app.mcp.registry import get_application_packet
from backend.app.models.application_packet import ApplicationPacket
from backend.tests.phase5a_fakes import approve, create
from backend.tests.test_mcp_tool_permissions import rpc

pytestmark = pytest.mark.asyncio

TOOLS = {
    "get_application_capabilities",
    "preview_job_application",
    "get_application_packet",
    "get_application_readiness",
    "get_application_handoff",
}


async def test_readonly_tool_registration_and_preview(
    mcp_client, mcp_auth, application_target, db_session
):
    result = await rpc(mcp_client, mcp_auth, "tools/list")
    names = {t["name"] for t in result["result"]["tools"]}
    assert TOOLS <= names
    assert not any(
        "submit" in n or "send" in n or "approve" in n or "login" in n for n in names
    )
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "preview_job_application",
            "arguments": {"job_id": str(application_target[0].id)},
        },
    )
    assert not result["result"].get("isError"), result
    assert "manual_handoff" in str(result)
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationPacket))
        == 0
    )


async def test_handoff_approval_cannot_be_bypassed(
    mcp_client, mcp_auth, packet_service, application_target
):
    packet = await create(packet_service, application_target[0])
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {"name": "get_application_handoff", "arguments": {"packet_id": str(packet.id)}},
    )
    assert "error" in result or result["result"].get("isError")
    packet = await approve(packet_service, packet)
    for name in TOOLS - {"get_application_capabilities", "preview_job_application"}:
        result = await rpc(
            mcp_client,
            mcp_auth,
            "tools/call",
            {"name": name, "arguments": {"packet_id": str(packet.id)}},
        )
        assert not result["result"].get("isError"), result


async def test_direct_call_requires_capability():
    from uuid import uuid4

    with pytest.raises(ToolError, match="authorized"):
        await get_application_packet(uuid4())


async def test_narrow_capability_scope_denied(mcp_client, mcp_auth, monkeypatch):
    from backend.app.mcp.auth import OwnerTokenVerifier

    original = OwnerTokenVerifier.verify_token

    async def narrow(self, token):
        result = await original(self, token)
        if result:
            result.scopes = ["read_profile"]
        return result

    monkeypatch.setattr(OwnerTokenVerifier, "verify_token", narrow)
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {"name": "get_application_capabilities", "arguments": {}},
    )
    assert "error" in result or result["result"].get("isError")
