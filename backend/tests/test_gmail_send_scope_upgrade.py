"""Explicit consent extends the existing encrypted PKCE connection without identity replacement."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.integrations.google_oauth import COMPOSE_SCOPES, SCOPES, SEND_SCOPES
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import CALLBACK, EMAIL, state_from
from backend.tests.test_gmail_connection import connect


@pytest.mark.asyncio
async def test_metadata_then_explicit_send_upgrade(oauth_bundle):
    service, fake, _ = oauth_bundle
    before = await connect(service)
    assert before["authorization_state"] == "metadata_connected"
    assert before["send_capability"] == "send_authorization_required"
    intent = await service.start(EMAIL, "browser", send=True)
    params = parse_qs(urlsplit(intent["authorization_url"]).query)
    assert set(params["scope"][0].split()) == SEND_SCOPES
    assert "consent" in params["prompt"][0] and params["code_challenge_method"] == [
        "S256"
    ]
    assert (await service.status())["authorization_state"] == "metadata_connected"
    fake.token["scope"] = " ".join(SEND_SCOPES)
    result = await service.callback(state_from(intent), "browser", CALLBACK, "upgrade")
    assert (
        result["id"] == before["id"]
        and result["google_subject"] == before["google_subject"]
    )
    assert result["authorization_state"] == "send_authorized"
    assert "fictional-access" not in str(result) and "fictional-refresh" not in str(
        result
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "no_send_scope",
        "extra_scope",
        "different_subject",
        "different_email",
        "no_refresh",
        "revoked",
        "denied",
    ],
)
async def test_failed_upgrade_preserves_metadata(oauth_bundle, failure):
    service, fake, _ = oauth_bundle
    await connect(service)
    before = await service.account()
    encrypted = before.encrypted_refresh_token
    intent = await service.start(EMAIL, "browser", send=True)
    fake.token["scope"] = " ".join(SEND_SCOPES)
    if failure == "no_send_scope":
        fake.token["scope"] = " ".join(SCOPES)
    elif failure == "extra_scope":
        fake.token["scope"] += " https://www.googleapis.com/auth/gmail.modify"
    elif failure == "different_subject":
        fake.identity["sub"] = "different-subject"
    elif failure == "different_email":
        fake.identity["email"] = fake.gmail_email = "other@example.com"
    elif failure == "no_refresh":
        del fake.token["refresh_token"]
    elif failure == "revoked":
        fake.fail = "/token"
    with pytest.raises(ConnectionError):
        await service.callback(
            state_from(intent),
            "browser",
            CALLBACK,
            "upgrade",
            error="access_denied" if failure == "denied" else None,
        )
    account = await service.account()
    assert (
        account.encrypted_refresh_token == encrypted
        and set(account.granted_scopes) == SCOPES
    )
    assert account.status == "connected"


@pytest.mark.asyncio
async def test_concurrent_upgrade_intents_only_latest_can_win(oauth_bundle):
    service, fake, _ = oauth_bundle
    await connect(service)
    first = state_from(await service.start(EMAIL, "browser", send=True))
    second = state_from(await service.start(EMAIL, "browser", send=True))
    fake.token["scope"] = " ".join(SEND_SCOPES)
    with pytest.raises(ConnectionError, match="superseded"):
        await service.callback(first, "browser", CALLBACK, "first")
    await service.callback(second, "browser", CALLBACK, "second")
    assert (await service.status())["send_capability"] == "send_authorized"


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
async def test_upgrade_requires_existing_connection(oauth_bundle):
    with pytest.raises(ConnectionError, match="metadata_connection"):
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
