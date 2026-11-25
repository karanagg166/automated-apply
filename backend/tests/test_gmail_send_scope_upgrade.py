"""Compose consent extends the PKCE connection; gmail.send upgrades are permanently refused."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.integrations.google_oauth import COMPOSE_SCOPES, SCOPES, SEND_SCOPES
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import CALLBACK, EMAIL, state_from
from backend.tests.test_gmail_connection import connect


@pytest.mark.asyncio
async def test_send_upgrade_is_refused_and_metadata_connection_preserved(oauth_bundle):
    """Gmail is read + draft only: a gmail.send upgrade can never be started."""
    service, fake, _ = oauth_bundle
    before = await connect(service)
    assert before["authorization_state"] == "metadata_connected"
    account = await service.account()
    encrypted, scopes = account.encrypted_refresh_token, set(account.granted_scopes)
    with pytest.raises(ConnectionError, match="gmail_send_scope_disabled"):
        await service.start(EMAIL, "browser", send=True)
    account = await service.account()
    assert account.encrypted_refresh_token == encrypted and set(account.granted_scopes) == scopes == SCOPES
    assert account.status == "connected"
    assert not any(b"gmail.send" in r.url.query or b"gmail.send" in r.content for r in fake.requests)
    assert (await service.status())["sending_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["silent_expansion", "revocation", "missing_scope", "same_scopes"]
)
async def test_refresh_never_silently_expands_scopes(oauth_bundle, mode):
    service, fake, _ = oauth_bundle
    await connect(service)
    account = await service.account()
    account.token_expires_at = now() - timedelta(seconds=1)
    await service.session.commit()
    if mode == "silent_expansion":
        fake.token["scope"] = " ".join(SEND_SCOPES)
    elif mode == "revocation":
        fake.fail = "/token"
    elif mode == "missing_scope":
        fake.token["scope"] = "openid email"
    if mode != "same_scopes":
        with pytest.raises(ConnectionError, match="reauthorization"):
            await service.access_token()
    else:
        assert await service.access_token() == "fictional-access"
    refresh_request = [
        r for r in fake.requests if b"grant_type=refresh_token" in r.content
    ][-1]
    assert b"scope=" not in refresh_request.content


@pytest.mark.asyncio
async def test_send_refused_even_without_existing_connection(oauth_bundle):
    with pytest.raises(ConnectionError, match="gmail_send_scope_disabled"):
        await oauth_bundle[0].start(EMAIL, "browser", send=True)


@pytest.mark.asyncio
async def test_compose_upgrade_keeps_identity_encrypted_tokens_and_sending_disabled(oauth_bundle):
    service, fake, settings = oauth_bundle
    before = await connect(service)
    intent = await service.start(EMAIL, "browser", compose=True)
    params = parse_qs(urlsplit(intent["authorization_url"]).query)
    assert set(params["scope"][0].split()) == COMPOSE_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in params["scope"][0]
    fake.token["scope"] = " ".join(COMPOSE_SCOPES)
    result = await service.callback(state_from(intent), "browser", CALLBACK, "compose-upgrade")
    assert result["id"] == before["id"] and result["google_subject"] == before["google_subject"]
    assert result["authorization_state"] == "compose_authorized"
    assert result["send_capability"] == "send_authorization_required"
    assert not settings.GMAIL_SENDING_ENABLED
    account = await service.account()
    assert account.encrypted_refresh_token != fake.token["refresh_token"]
    assert "fictional-access" not in str(result) and "fictional-refresh" not in str(result)
    account.token_expires_at = now() - timedelta(seconds=1)
    await service.session.commit()
    assert await service.access_token() == "fictional-access"
    assert (await service.status())["authorization_state"] == "compose_authorized"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["send_scope", "extra_scope", "different_subject", "different_email", "no_refresh", "denied"])
async def test_failed_compose_consent_preserves_connected_metadata(oauth_bundle, failure):
    service, fake, _ = oauth_bundle
    await connect(service)
    encrypted = (await service.account()).encrypted_refresh_token
    intent = await service.start(EMAIL, "browser", compose=True)
    fake.token["scope"] = " ".join(COMPOSE_SCOPES)
    if failure == "send_scope":
        fake.token["scope"] = " ".join(SEND_SCOPES)
    elif failure == "extra_scope":
        fake.token["scope"] += " https://www.googleapis.com/auth/gmail.modify"
    elif failure == "different_subject":
        fake.identity["sub"] = "wrong-subject"
    elif failure == "different_email":
        fake.identity["email"] = fake.gmail_email = "wrong@example.org"
    elif failure == "no_refresh":
        del fake.token["refresh_token"]
    with pytest.raises(ConnectionError):
        await service.callback(state_from(intent), "browser", CALLBACK, "compose-upgrade",
            error="access_denied" if failure == "denied" else None)
    account = await service.account()
    assert account.status == "connected" and set(account.granted_scopes) == SCOPES
    assert account.encrypted_refresh_token == encrypted


@pytest.mark.asyncio
async def test_compose_database_mismatch_is_recoverable_without_identity_change(oauth_bundle, monkeypatch):
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import IntegrityError

    service, _, _ = oauth_bundle
    await connect(service)
    before = (await service.account()).encrypted_refresh_token

    class DriverFailure(Exception):
        sqlstate = "23514"
        constraint_name = "oauth_states_authorization_mode_check"

    failure = IntegrityError("private SQL", {"private": "never disclose"}, DriverFailure())
    with monkeypatch.context() as patch:
        patch.setattr(service.session, "commit", AsyncMock(side_effect=failure))
        with pytest.raises(ConnectionError, match="^gmail_compose_schema_update_required$"):
            await service.start(EMAIL, "browser", compose=True)
    account = await service.account()
    assert account.status == "connected" and account.encrypted_refresh_token == before
    assert set(account.granted_scopes) == SCOPES


@pytest.mark.asyncio
async def test_compose_setup_error_returns_actionable_409(oauth_bundle, phase2_auth, monkeypatch):
    import httpx

    from backend.app.api.v1.integrations import connection_service
    from backend.app.main import app
    service, _, _ = oauth_bundle
    async def blocked(*args, **kwargs):
        raise ConnectionError("gmail_compose_schema_update_required")
    monkeypatch.setattr(service, "start", blocked)
    app.dependency_overrides[connection_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://localhost") as client:
            response = await client.post("/api/v1/integrations/gmail/connect/start",
                headers=phase2_auth, json={"expected_email": EMAIL, "authorization_mode": "compose"})
        assert response.status_code == 409
        assert "setup update" in response.json()["detail"]
        assert "identity remains connected" in response.json()["detail"]
        assert "set-cookie" not in response.headers
    finally:
        app.dependency_overrides.pop(connection_service)
