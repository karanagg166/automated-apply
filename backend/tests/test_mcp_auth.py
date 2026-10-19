"""Authentication protects all mounted paths before protocol initialization."""

import pytest

from backend.app.core.config import get_settings
from backend.app.mcp.auth import OwnerTokenVerifier

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "tests", "version": "1"},
    },
}


@pytest.mark.asyncio
async def test_remote_disabled(async_client):
    response = await async_client.post("/mcp/", json=INIT)
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/mcp", "/mcp/", "/mcp/sse", "/mcp/messages", "/mcp/nested/session"]
)
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_entire_mount_denies_unauthenticated(mcp_client, path, method):
    response = await mcp_client.request(method, path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_invalid_and_profile_tokens_denied(mcp_client, phase2_auth):
    for headers in ({"Authorization": "Bearer invalid"}, phase2_auth):
        assert (
            await mcp_client.post("/mcp/", json=INIT, headers=headers)
        ).status_code == 401


@pytest.mark.asyncio
async def test_missing_server_token_fails_closed(mcp_client, monkeypatch):
    monkeypatch.setenv("MCP_API_TOKEN", "")
    get_settings.cache_clear()
    assert (await mcp_client.post("/mcp/", json=INIT)).status_code == 503


@pytest.mark.asyncio
async def test_reused_profile_token_not_accepted(monkeypatch):
    monkeypatch.setenv("MCP_REMOTE_ENABLED", "true")
    for key in ("MCP_API_TOKEN", "JOB_AGENT_API_TOKEN"):
        monkeypatch.setenv(key, "same-token-with-32-or-more-characters")
    get_settings.cache_clear()
    assert (
        await OwnerTokenVerifier().verify_token("same-token-with-32-or-more-characters")
        is None
    )
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_authorized_initialization(mcp_client, mcp_auth):
    response = await mcp_client.post("/mcp/", json=INIT, headers=mcp_auth)
    assert response.status_code == 200, response.text
    assert "serverInfo" in response.json()["result"]
    assert "mcp-session-id" not in response.headers  # stateless requests
