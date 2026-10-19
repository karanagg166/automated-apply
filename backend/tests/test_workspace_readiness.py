"""Cross-service failures must be visible before a private workspace deployment."""

import json
import secrets

import pytest
from cryptography.fernet import Fernet

from backend.app.core.config import Settings
from backend.app.operations.configuration import target_identity
from backend.app.operations.workspace import FrontendSettings, workspace_readiness


def workspace(**frontend_overrides):
    backend = Settings(
        _env_file=None, ENVIRONMENT="staging",
        DATABASE_URL="postgresql+asyncpg://owner:private-db-password@isolated.invalid/staging",  # pragma: allowlist secret — fictional, no connection
        JOB_AGENT_API_TOKEN=secrets.token_urlsafe(48), SECRET_KEY=secrets.token_urlsafe(48),
        RESUME_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        API_ALLOWED_HOSTS=["api.staging.invalid"],
    )
    backend.STAGING_DATABASE_ID = target_identity(backend)
    frontend = FrontendSettings(_env_file=None, **{
        "FRONTEND_ORIGIN": "https://workspace.staging.invalid",
        "BACKEND_ORIGIN": "https://api.staging.invalid",
        "FRONTEND_SESSION_SECRET": secrets.token_urlsafe(48),
        "FRONTEND_PASSWORD_HASH": "a" * 32 + ":" + "b" * 128,
        **frontend_overrides,
    })
    return backend, frontend


def test_valid_configuration_never_claims_operational_readiness():
    backend, frontend = workspace()
    report = workspace_readiness(backend, frontend)
    assert report["status"] == "configured_not_verified"
    assert not any(report[key] for key in (
        "production_ready", "database_connected", "staging_deployed",
        "owner_login_verified", "backup_restore_verified",
    ))
    rendered = json.dumps(report)
    for private in ("private-db-password", "isolated.invalid", frontend.FRONTEND_PASSWORD_HASH.get_secret_value(), frontend.FRONTEND_SESSION_SECRET.get_secret_value()):
        assert private not in rendered


@pytest.mark.parametrize("overrides", [
    {"FRONTEND_ORIGIN": "http://workspace.staging.invalid"},
    {"FRONTEND_ORIGIN": "https://workspace.staging.invalid/extra"},
    {"FRONTEND_ORIGIN": "https://owner:password@workspace.staging.invalid"},  # pragma: allowlist secret — rejected fixture
    {"FRONTEND_ORIGIN": "https://workspace.staging.invalid:invalid"},
    {"BACKEND_ORIGIN": "http://api.staging.invalid"},
    {"BACKEND_ORIGIN": "https://wrong.staging.invalid"},
    {"FRONTEND_LOCAL_HTTP": True},
    {"FRONTEND_PASSWORD_HASH": "default-password"},  # pragma: allowlist secret — rejected fixture
    {"FRONTEND_SESSION_SECRET": "short"},  # pragma: allowlist secret — rejected fixture
])
def test_invalid_frontend_configuration_blocks_workspace(overrides):
    backend, frontend = workspace(**overrides)
    assert workspace_readiness(backend, frontend)["status"] == "needs_configuration"


def test_api_and_session_secrets_must_be_independent():
    backend, frontend = workspace()
    frontend.FRONTEND_SESSION_SECRET = backend.JOB_AGENT_API_TOKEN
    assert workspace_readiness(backend, frontend)["status"] == "needs_configuration"


@pytest.mark.parametrize("key", [None, "invalid-private-key"])
def test_private_resume_storage_requires_a_valid_dedicated_key(key):
    backend, frontend = workspace()
    backend.RESUME_ENCRYPTION_KEY = key
    report = workspace_readiness(backend, frontend)
    check = next(c for c in report["checks"] if c["name"] == "private_resume_encryption")
    assert check["required"] and check["status"] == "missing_configuration"
    assert report["status"] == "needs_configuration"


def test_oauth_callback_must_share_frontend_origin_when_enabled():
    backend, frontend = workspace()
    backend.GMAIL_REDIRECT_URI = "https://api.staging.invalid/api/v1/integrations/gmail/oauth/callback"
    assert workspace_readiness(backend, frontend)["status"] == "needs_configuration"
    backend.GMAIL_REDIRECT_URI = "https://workspace.staging.invalid/api/v1/integrations/gmail/oauth/callback"
    assert workspace_readiness(backend, frontend)["status"] == "configured_not_verified"
