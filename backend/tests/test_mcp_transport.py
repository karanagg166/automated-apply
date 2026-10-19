"""Real HTTP transport and full-path ASGI resource/cancellation boundaries."""

import asyncio

import httpx
import pytest

from backend.app.core.config import get_settings
from backend.app.mcp.auth import MCPBoundary
from backend.tests.test_mcp_auth import INIT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,code",
    [({"Host": "evil.example"}, 421), ({"Origin": "https://evil.example"}, 403)],
)
async def test_native_host_origin_guard(mcp_client, mcp_auth, headers, code):
    response = await mcp_client.post(
        "/mcp/", json=INIT, headers={**mcp_auth, **headers}
    )
    assert response.status_code == code, response.text


@pytest.mark.asyncio
async def test_unauthorized_streaming_denied(mcp_client):
    async with mcp_client.stream(
        "GET", "/mcp/", headers={"Accept": "text/event-stream"}
    ) as response:
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_malformed_request(mcp_client, mcp_auth):
    response = await mcp_client.post("/mcp/", headers=mcp_auth, content="{malformed")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_request_size_bounded(mcp_client, mcp_auth):
    response = await mcp_client.post("/mcp/", headers=mcp_auth, content=b"x" * 65537)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_tls_required(mcp_client, mcp_auth):
    response = await mcp_client.post(
        "http://localhost/mcp/", headers=mcp_auth, json=INIT
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_concurrency_timeout_and_cancellation(mcp_auth, monkeypatch):
    monkeypatch.setenv("MCP_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("MCP_REQUEST_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(scope, receive, send):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPBoundary(slow)),
        base_url="https://localhost",
    ) as client:
        first = asyncio.create_task(client.post("/mcp/", headers=mcp_auth))
        await entered.wait()
        assert (await client.post("/mcp/", headers=mcp_auth)).status_code == 429
        assert (await first).status_code == 504
        assert cancelled.is_set()
        entered.clear()
        task = asyncio.create_task(client.post("/mcp/", headers=mcp_auth))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Admission is released even when the client cancels.
        assert (await client.post("/mcp/", headers=mcp_auth)).status_code == 504


@pytest.mark.asyncio
async def test_mount_root_also_checks_host_origin(mcp_client, mcp_auth):
    assert (
        await mcp_client.post(
            "/mcp", headers={**mcp_auth, "Host": "evil.example"}, json=INIT
        )
    ).status_code == 421
    assert (
        await mcp_client.post(
            "/mcp", headers={**mcp_auth, "Origin": "https://evil.example"}, json=INIT
        )
    ).status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("MCP_ALLOWED_HOSTS", ["*"]),
        ("MCP_ALLOWED_HOSTS", []),
        ("MCP_ALLOWED_ORIGINS", ["https://*.example.com"]),
        ("MCP_ALLOWED_ORIGINS", ["https://example.com/path"]),
    ],
)
def test_wildcard_trust_rejected(field, value):
    from backend.app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.asyncio
async def test_concurrent_native_tool_requests(mcp_client, mcp_auth):
    async def request(i):
        return await mcp_client.post(
            "/mcp/",
            headers=mcp_auth,
            json={"jsonrpc": "2.0", "id": i, "method": "tools/list", "params": {}},
        )

    responses = await asyncio.gather(*(request(i) for i in range(12)))
    assert any(r.status_code == 200 for r in responses)
    assert all(r.status_code in {200, 429} for r in responses)
    for response in responses:
        if response.status_code == 200:
            assert response.json()["result"]["tools"]


@pytest.mark.asyncio
async def test_local_stdio_connection_supports_read_only_tools():
    import os
    import sys
    from pathlib import Path

    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    environment = {
        **os.environ,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "MCP_REMOTE_ENABLED": "false",
        "MCP_ALLOW_DRAFT_CREATION": "false",
    }
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "backend.app.mcp.registry"],
        env=environment,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    async with Client(transport) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert "list_discovery_sources" in tools
        # stdio discovery skips OAuth filtering; the function still denies prepare_draft.
        result = await client.call_tool("list_discovery_sources", {})
        assert result.content and not result.is_error
        with pytest.raises(Exception, match="authorized"):
            await client.call_tool(
                "prepare_founder_outreach_draft",
                {"contact_id": "00000000-0000-0000-0000-000000000001"},
            )
