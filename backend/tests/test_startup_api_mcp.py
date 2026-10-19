import pytest
from sqlalchemy import func, select

from backend.app.models.discovery import DiscoveryRun
from backend.app.models.startup import CompanySourceObservation
from backend.app.services.startup_discovery.evidence import ingest_company
from backend.tests.startup_fakes import observed
from backend.tests.test_mcp_tool_permissions import rpc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "sources"),
        ("GET", "search"),
        ("GET", "shortlist"),
        ("GET", "integrations/status"),
        ("POST", "discovery/preview"),
        ("POST", "discovery/runs"),
        ("POST", "integrations/arbeitnow/check"),
        ("GET", "invalid/evidence"),
    ],
)
async def test_startup_auth_before_validation(async_client, phase2_auth, method, path):
    result = await async_client.request(
        method,
        "/api/v1/startups/" + path,
        headers={"Authorization": "Bearer wrong"},
        content=b"invalid",
    )
    assert result.status_code == 401
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_startup_routes_preview_import_shortlist_and_validation(
    async_client, phase2_auth, db_session
):
    body = dict(
        mode="company_first",
        source="manual",
        idempotency_key="api-startup-001",
        companies=[observed().model_dump(mode="json")],
        permission_confirmed=True,
    )
    preview = await async_client.post(
        "/api/v1/startups/discovery/preview", headers=phase2_auth, json=body
    )
    assert preview.status_code == 200 and preview.json()["provider_calls"] == 0
    assert await db_session.scalar(select(func.count()).select_from(DiscoveryRun)) == 0
    result = await async_client.post(
        "/api/v1/startups/discovery/runs", headers=phase2_auth, json=body
    )
    assert result.status_code == 200 and result.json()["status"] == "success", (
        result.text
    )
    company_id = result.json()["rankings"][0]["company_id"]
    for path in [
        "/search?include_unknown_size=false",
        "/" + company_id,
        "/" + company_id + "/jobs",
        "/" + company_id + "/evidence",
        "/discovery/runs/" + result.json()["id"],
        "/integrations/status",
    ]:
        response = await async_client.get(
            "/api/v1/startups" + path, headers=phase2_auth
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
    for _ in range(2):
        response = await async_client.post(
            f"/api/v1/startups/{company_id}/shortlist",
            headers=phase2_auth,
            json={"note": "Reviewed fictional company"},
        )
        assert response.status_code == 200
    response = await async_client.get("/api/v1/startups/shortlist", headers=phase2_auth)
    assert response.json()["total"] == 1
    response = await async_client.post(
        "/api/v1/startups/search", headers=phase2_auth, json={"skills": ["Python"]}
    )
    assert response.json()["total"] == 1
    response = await async_client.get(
        "/api/v1/startups/search?max_employees=-1", headers=phase2_auth
    )
    assert response.status_code == 422 and response.json() == {
        "detail": "Invalid request"
    }
    body["allow_paid"] = True
    assert (
        await async_client.post(
            "/api/v1/startups/discovery/runs", headers=phase2_auth, json=body
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_startup_readonly_mcp_matches_rest_service(
    mcp_client, mcp_auth, db_session
):
    company = await ingest_company(db_session, observed())
    await db_session.commit()
    listing = await rpc(mcp_client, mcp_auth, "tools/list")
    names = {t["name"] for t in listing["result"]["tools"]}
    expected = {
        "search_discovered_startups",
        "get_startup_intelligence",
        "get_startup_hiring_opportunities",
        "get_startup_professional_contacts",
        "get_startup_discovery_status",
    }
    assert expected <= names
    for name in expected:
        args = (
            {"filters": {}}
            if name == "search_discovered_startups"
            else {}
            if name == "get_startup_discovery_status"
            else {"company_id": str(company.id)}
        )
        result = await rpc(
            mcp_client, mcp_auth, "tools/call", {"name": name, "arguments": args}
        )
        assert not result["result"].get("isError"), result
    assert await db_session.scalar(select(func.count()).select_from(DiscoveryRun)) == 0
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CompanySourceObservation)
        )
        == 1
    )
