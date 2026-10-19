"""Readiness is configuration evidence, never an implicit live test."""

import json

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.operations.configuration import (
    OperationRejected,
    load_settings,
    require_staging,
    target_identity,
)
from backend.app.operations.readiness import environment_readiness, require_safe_startup


def settings(**overrides):
    return Settings(_env_file=None, **{"ENVIRONMENT": "staging", "DATABASE_URL": "postgresql+asyncpg://operator:private-db-password@staging.invalid/staging", **overrides})


def test_configuration_never_claims_live_verification():
    config = settings(GEMINI_API_KEY="private-gemini-key", LLM_MODEL="gemini-configured-model")
    report = environment_readiness(config)
    rendered = report.model_dump_json()
    assert not report.production_ready
    assert not report.database_connected
    assert "private-gemini-key" not in rendered
    assert "private-db-password" not in rendered
    assert "staging.invalid" not in rendered
    assert next(c for c in report.checks if c.name == "gemini").status == "configured_not_verified"


@pytest.mark.parametrize("url", ["", "sqlite+aiosqlite:///:memory:", "postgresql+asyncpg:///missing-host"])
def test_missing_or_invalid_live_database(url):
    report = environment_readiness(settings(DATABASE_URL=url))
    assert report.status == "needs_configuration"
    assert next(c for c in report.checks if c.name == "database").status == "missing_configuration"


@pytest.mark.parametrize("schema", ["public", "other_schema"])
def test_migrations_require_expected_schema(schema):
    assert environment_readiness(settings(DATABASE_SCHEMA=schema)).status == "needs_configuration"


@pytest.mark.parametrize("schema", ["x; DROP SCHEMA job_agent", "", "jobs/path"])
def test_invalid_schema_rejected(schema):
    with pytest.raises(ValidationError):
        settings(DATABASE_SCHEMA=schema)


def test_production_target_rejected_before_any_connection():
    config = settings(ENVIRONMENT="production")
    config.STAGING_DATABASE_ID = target_identity(config)
    with pytest.raises(OperationRejected, match="production_connections_forbidden"):
        require_staging(config, config.STAGING_DATABASE_ID)


def test_target_pin_requires_two_explicit_matches():
    config = settings()
    target = target_identity(config)
    with pytest.raises(OperationRejected):
        require_staging(config, target)
    config.STAGING_DATABASE_ID = target
    with pytest.raises(OperationRejected):
        require_staging(config, "other")
    assert require_staging(config, target) == target
    config.DATABASE_URL = config.DATABASE_URL.replace("staging.invalid", "production.invalid")
    with pytest.raises(OperationRejected):
        require_staging(config, target)


def test_missing_gemini_and_gmail_remain_truthful():
    checks = {c.name: c.status for c in environment_readiness(settings()).checks}
    assert checks["gemini"] == "missing_credentials"
    assert checks["gmail"] == "not_connected"
    assert checks["gmail_sending_disabled"] == "configured_not_verified"


@pytest.mark.parametrize("model", ["http://secret.invalid/key", "other-model", "gemini-key?api_key=private"])
def test_invalid_gemini_model(model):
    with pytest.raises(ValidationError):
        settings(LLM_MODEL=model)


@pytest.mark.parametrize("overrides", [{"DEBUG": True}, {"DB_ECHO": True}, {"MCP_REMOTE_ENABLED": True}, {"GMAIL_SENDING_ENABLED": True}])
def test_staging_fails_closed_on_unsafe_settings(overrides):
    with pytest.raises(OperationRejected):
        require_safe_startup(settings(**overrides))


def test_submission_cannot_be_enabled():
    with pytest.raises(ValidationError):
        settings(APPLICATION_SUBMISSION_ENABLED=True)


def test_invalid_configuration_errors_redact_input(tmp_path, monkeypatch):
    path = tmp_path / "bad.env"
    path.write_text('LLM_MODEL="https://private.invalid/private-key"\n')
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(OperationRejected) as captured:
        load_settings(path)
    assert "private-key" not in str(captured.value)
    assert "LLM_MODEL" in str(captured.value)


def test_passing_static_checks_are_still_unverified():
    config = settings(JOB_AGENT_API_TOKEN="Zx73q-5wF9ajTnsuCRv0LP8YrbD6K2eH", SECRET_KEY="F32gH7vkBZ5Nm_ae98xqP0ucTw6RjLsy", API_ALLOWED_HOSTS=["staging.invalid"], RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode())
    config.STAGING_DATABASE_ID = target_identity(config)
    report = environment_readiness(config)
    assert report.status == "configured_not_verified"
    assert not json.loads(report.model_dump_json())["production_ready"]


def test_dotenv_fixed_controls_parse_without_weakening_invariants(tmp_path):
    path = tmp_path / "controls.env"
    path.write_text("APPLICATION_SUBMISSION_ENABLED=false\nGMAIL_REQUIRE_EXPLICIT_CONFIRMATION=true\nGMAIL_SEND_MAX_RECIPIENTS=1\n")
    config = load_settings(path)
    assert config.APPLICATION_SUBMISSION_ENABLED is False
    assert config.GMAIL_REQUIRE_EXPLICIT_CONFIRMATION is True
    assert config.GMAIL_SEND_MAX_RECIPIENTS == 1


def test_dsn_query_target_overrides_cannot_bypass_pin():
    config = settings(DATABASE_URL="postgresql+asyncpg://user:password@staging.invalid/db?host=production.invalid")
    with pytest.raises(OperationRejected):
        target_identity(config)
