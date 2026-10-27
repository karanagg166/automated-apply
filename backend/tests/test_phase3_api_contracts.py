"""Real API responses and generated-client contracts; isolated fictional facts."""

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.models.discovery import DiscoveryMonthlyBudget


async def test_explicit_missing_create_without_storage_is_conflict(
    async_client, db_session, phase2_profile, phase2_auth
):
    await db_session.execute(text("DROP TABLE owner_preferences"))
    response = await async_client.post(
        "/api/v1/application-answers/missing",
        headers=phase2_auth,
        json={"question": "Expected salary", "missing_fact": "Owner compensation"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "missing_input_storage_schema_required"


async def test_explicit_create_returns_typed_resource_and_history(
    async_client, phase2_profile, phase2_auth
):
    path = "/api/v1/application-answers/missing"
    created = await async_client.post(
        path,
        headers=phase2_auth,
        json={"question": "Expected salary", "missing_fact": "Owner compensation"},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == item["effective_status"] == "needs_input"
    assert not item["ever_approved"] and not item["stale"]
    assert item["answer"] is None and item["profile_version"] == phase2_profile.version
    loaded = await async_client.get(item["href"], headers=phase2_auth)
    assert loaded.json() == item
    history = await async_client.get(item["href"] + "/history", headers=phase2_auth)
    assert history.json() == {"history": []}


def test_missing_and_apify_outputs_are_available_to_generated_clients():
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/application-answers/missing", "get", "200"): "MissingInputList",
        ("/api/v1/application-answers/missing", "post", "201"): "MissingInputRead",
        ("/api/v1/application-answers/missing/{request_id}", "patch", "200"): "MissingInputRead",
        ("/api/v1/application-answers/missing/{request_id}/approve", "post", "200"): "MissingInputRead",
        ("/api/v1/application-answers/missing/{request_id}/history", "get", "200"): "MissingInputHistory",
        ("/api/v1/integrations/providers/apify", "get", "200"): "ApifyStatus",
        ("/api/v1/integrations/providers/apify/actors/inspect", "post", "200"): "ActorMetadata",
    }
    for (path, method, status), name in expected.items():
        schema = paths[path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"] == "#/components/schemas/" + name


async def test_apify_budget_is_local_reserved_and_never_provider_authorization(
    async_client, db_session, phase2_auth, monkeypatch
):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    db_session.add(DiscoveryMonthlyBudget(provider="apify", month=month, reserved=Decimal("1.25")))
    await db_session.commit()
    monkeypatch.setenv("APIFY_MONTHLY_LIMIT_USD", "2")
    get_settings.cache_clear()
    try:
        response = await async_client.get("/api/v1/integrations/providers/apify", headers=phase2_auth)
        assert response.status_code == 200
        result = response.json()
        assert result["local_budget"] == {
            "month": month, "reserved_usd": 1.25, "remaining_local_usd": 0.75,
            "accounting": "local_reservations_not_provider_credit",
        }
        assert not result["execution_authorized"] and not result["account_rotation"]
        assert result["last_account_inspection"] is None
        assert result["sources"] and all(s["id"] != "apify" for s in result["sources"])
        assert response.headers["cache-control"] == "no-store"
    finally:
        get_settings.cache_clear()


async def test_unreviewed_actor_configuration_does_not_claim_authorization(
    async_client, phase2_auth, monkeypatch
):
    monkeypatch.setenv("APIFY_API_TOKEN", "fictional-test-token")
    monkeypatch.setenv("APIFY_SOURCES", json.dumps({"naukri": {"actor_id": "unreviewed/actor"}}))
    get_settings.cache_clear()
    try:
        response = await async_client.get("/api/v1/dashboard/connections", headers=phase2_auth)
        provider = next(p for p in response.json()["providers"] if p["provider"] == "apify")
        assert provider["configured"] and not provider["authorized"]
    finally:
        get_settings.cache_clear()
