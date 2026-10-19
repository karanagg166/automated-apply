"""Optional integrations do not gate process health or expose private data in diagnostics."""

import pytest

from backend.app.core.config import Settings
from backend.app.operations.boundary import transport_error
from backend.app.operations.diagnostics import (
    gmail_readiness,
    operational_status,
    paid_readiness,
)
from backend.app.operations.readiness import require_safe_startup


@pytest.mark.parametrize("scheme,host,origins,expected", [
    ("http", "staging.invalid", [], "https_required"),
    ("https", "attacker.invalid", [], "untrusted_host"),
    ("https", "staging.invalid", ["https://attacker.invalid"], "untrusted_origin"),
    ("https", "staging.invalid", [], None),
])
def test_transport_boundary(scheme, host, origins, expected):
    config = Settings(_env_file=None, ENVIRONMENT="staging", API_ALLOWED_HOSTS=["staging.invalid"])
    assert transport_error(config, scheme, host, origins) == expected


@pytest.mark.asyncio
async def test_missing_gmail_does_not_claim_connection(db_session):
    result = await gmail_readiness(db_session, Settings(_env_file=None))
    assert result["status"] == "not_connected"
    assert not result["sending_enabled"]
    assert not result["sender_identity_matches"]


@pytest.mark.asyncio
async def test_diagnostics_do_not_write_or_contact_providers(db_session):
    from backend.app.db.session import get_session_factory
    result = await operational_status(db_session, get_session_factory(), Settings(_env_file=None))
    assert result["external_calls"] == 0
    assert result["profile"]["status"] == "blocked"
    assert not db_session.new
    assert not db_session.dirty
    assert all(not p["live_verified"] for p in result["providers"]["providers"])


def test_paid_configuration_never_authorizes_a_request():
    config = Settings(_env_file=None, APOLLO_API_KEY="private-apollo", APOLLO_ENRICHMENT_ENABLED=True,
                      APOLLO_CREDITS_PER_LOOKUP=1)
    result = paid_readiness(config)
    apollo = next(p for p in result if p["provider"] == "apollo")
    assert apollo["configured"]
    assert apollo["status"] == "authorization_required"
    assert not apollo["paid_execution_enabled"]
    assert apollo["latest_successful_test"] is None
    assert "private-apollo" not in str(result)


@pytest.mark.asyncio
async def test_readiness_exception_is_redacted(async_client, monkeypatch, caplog):
    import backend.app.main as main

    def broken():
        raise RuntimeError("postgresql://private-user:private-password@private-host/db")

    monkeypatch.setattr(main, "get_engine", broken)
    response = await async_client.get("/ready")
    assert response.status_code == 503
    assert "private-password" not in response.text + caplog.text
    assert response.json()["error"] == "database_unavailable"


@pytest.mark.asyncio
async def test_credits_and_operations_require_authentication(async_client):
    for route in ("/api/v1/credits/status", "/api/v1/operations/status"):
        response = await async_client.get(route)
        assert response.status_code in (401, 503)
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_private_profile_validation_does_not_echo_input(async_client, phase2_auth):
    response = await async_client.put("/api/v1/profile", headers=phase2_auth, json={"email": "private-person-invalid-email"})
    assert response.status_code == 422
    assert "private-person" not in response.text


def test_missing_staging_config_fails_startup():
    with pytest.raises(ValueError, match="unsafe_deployment_configuration"):
        require_safe_startup(Settings(_env_file=None, ENVIRONMENT="staging"))


@pytest.mark.asyncio
async def test_optional_provider_outage_keeps_liveness_available(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200


def test_application_log_filter_redacts_database_credentials(monkeypatch):
    import logging

    from backend.app.core.config import get_settings
    from backend.app.core.logging import SecretRedactionFilter
    monkeypatch.setattr(get_settings(), "DATABASE_URL", "postgresql+asyncpg://owner:private-password@host.invalid/db")
    record = logging.LogRecord("test", logging.ERROR, "test", 1, "connection failed %s", ("private-password",), None)
    SecretRedactionFilter().filter(record)
    assert "private-password" not in record.getMessage()


@pytest.mark.asyncio
async def test_live_profile_api_rejects_placeholder_data(db_session, phase2_profile, monkeypatch):
    from backend.app.core.config import get_settings
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.app.services.candidate_profile_service import CandidateProfileService
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "staging")
    with pytest.raises(ValueError, match="placeholder"):
        await CandidateProfileService(db_session).upsert_profile(CandidateProfileCreate.model_validate(phase2_profile))


@pytest.mark.parametrize("host", ["[", "user@staging.invalid", "staging.invalid?extra", "staging.invalid/path", "staging.invalid:invalid"])
def test_malformed_hosts_fail_closed(host):
    config = Settings(_env_file=None, ENVIRONMENT="staging", API_ALLOWED_HOSTS=["staging.invalid"])
    assert transport_error(config, "https", host, []) == "untrusted_host"
