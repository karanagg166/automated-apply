"""Discovery filtering and independent call denial; no paid or delivery tool exists."""

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.mcp.permissions import LEGACY_CAPABILITIES
from backend.app.mcp.registry import get_verified_profile_summary
from backend.app.models.company import Company
from backend.app.models.outreach import OutreachLog


async def rpc(client, headers, method, params=None):
    response = await client.post(
        "/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_read_only_listing(mcp_client, mcp_auth):
    response = await rpc(mcp_client, mcp_auth, "tools/list")
    tools = {t["name"] for t in response["result"]["tools"]}
    assert "get_verified_profile_summary" in tools
    assert "prepare_founder_outreach_draft" not in tools
    assert not tools.intersection(LEGACY_CAPABILITIES)
    assert not any("send" in t or "submit" in t for t in tools)


@pytest.mark.asyncio
async def test_privileged_legacy_call_denied_without_mutation(
    mcp_client, mcp_auth, db_session
):
    for name in LEGACY_CAPABILITIES:
        response = await rpc(
            mcp_client, mcp_auth, "tools/call", {"name": name, "arguments": {}}
        )
        assert "error" in response or response["result"].get("isError")
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 0
    assert await db_session.scalar(select(func.count()).select_from(OutreachLog)) == 0


@pytest.mark.asyncio
async def test_undiscovered_draft_call_denied(mcp_client, mcp_auth, outreach_target):
    contact = outreach_target[0]
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "prepare_founder_outreach_draft",
            "arguments": {"contact_id": str(contact.id)},
        },
    )
    assert "error" in result or result["result"].get("isError")


@pytest.mark.asyncio
async def test_draft_opt_in_uses_same_service_no_provider(
    mcp_client, mcp_auth, outreach_target, monkeypatch
):
    monkeypatch.setenv("MCP_ALLOW_DRAFT_CREATION", "true")
    get_settings.cache_clear()
    contact, _, job, _ = outreach_target
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "prepare_founder_outreach_draft",
            "arguments": {"contact_id": str(contact.id), "job_id": str(job.id)},
        },
    )
    assert not result["result"].get("isError"), result
    text = str(result)
    assert "pending_approval" in text and "mcp" in text
    assert "fictional-refresh" not in text


@pytest.mark.asyncio
async def test_private_wrapper_denies_direct_unauthenticated_call():
    with pytest.raises(ToolError, match="authorized"):
        await get_verified_profile_summary()


@pytest.mark.asyncio
async def test_persisted_profile_match_no_resubmitted_identity(
    mcp_client, mcp_auth, outreach_target
):
    job = outreach_target[2]
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "match_job_against_saved_profile",
            "arguments": {"job_id": str(job.id)},
        },
    )
    assert not result["result"].get("isError"), result
    assert "Python" in str(result)


@pytest.mark.asyncio
async def test_mcp_input_validation(mcp_client, mcp_auth):
    result = await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {"name": "search_saved_jobs", "arguments": {"limit": 100000}},
    )
    assert "error" in result or result["result"].get("isError")


@pytest.mark.asyncio
async def test_audit_contains_only_sanitized_metadata(mcp_client, mcp_auth, caplog):
    import json
    import logging

    caplog.set_level(logging.INFO, logger="job_pulse_agent.mcp.audit")
    await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "search_saved_jobs",
            "arguments": {"status": "private-resume-in-invalid-input"},
        },
    )
    audits = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "job_pulse_agent.mcp.audit"
    ]
    assert audits and audits[-1]["actor_id"] == "owner"
    assert set(audits[-1]) == {
        "timestamp",
        "tool",
        "outcome",
        "request_id",
        "actor_id",
        "duration_ms",
        "error_category",
    }
    assert "private-resume-in-invalid-input" not in str(audits)
    assert "fictional-mcp-owner-token" not in str(audits)


@pytest.mark.asyncio
async def test_denied_legacy_invocation_is_audited(mcp_client, mcp_auth, caplog):
    import json
    import logging

    caplog.set_level(logging.INFO, logger="job_pulse_agent.mcp.audit")
    await rpc(
        mcp_client,
        mcp_auth,
        "tools/call",
        {
            "name": "save_discovered_job",
            "arguments": {"description": "private-description"},
        },
    )
    audits = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "job_pulse_agent.mcp.audit"
    ]
    assert audits and audits[-1]["tool"] == "save_discovered_job"
    assert audits[-1]["outcome"] == "denied"
    assert "private-description" not in str(audits)
