"""Authorization code, PKCE, browser binding, exact redirects and one-time durable state."""

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.connected_account import OAuthState
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import CALLBACK, EMAIL, state_from


@pytest.mark.asyncio
async def test_authorization_url_state_pkce(oauth_bundle, db_session):
    service, _, settings = oauth_bundle
    result = await service.start(EMAIL, "browser-secret")
    params = parse_qs(urlsplit(result["authorization_url"]).query)
    assert params["redirect_uri"] == [CALLBACK]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent select_account"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["login_hint"] == [EMAIL]
    assert not any(
        s in params["scope"][0]
        for s in ("gmail.send", "gmail.compose", "gmail.readonly", "mail.google.com")
    )
    intent = await db_session.scalar(select(OAuthState))
    assert intent.state_hash != params["state"][0]
    verifier = TokenStore(settings).decrypt(
        intent.encrypted_verifier, intent.state_hash
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert params["code_challenge"] == [challenge]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["forged", "expired", "browser", "redirect", "denied", "code"]
)
async def test_callback_rejects_invalid_intent(oauth_bundle, db_session, failure):
    service, fake, _ = oauth_bundle
    state = state_from(await service.start(EMAIL, "browser"))
    browser, redirect, code, error = "browser", CALLBACK, "valid-code", None
    if failure == "forged":
        state = "forged-state"
    elif failure == "expired":
        intent = await db_session.scalar(select(OAuthState))
        intent.expires_at = now() - timedelta(seconds=1)
        await db_session.commit()
    elif failure == "browser":
        browser = "attacker-browser"
    elif failure == "redirect":
        redirect = "https://evil.example/callback"
    elif failure == "denied":
        error = "access_denied"
    elif failure == "code":
        code = None
    with pytest.raises(ConnectionError):
        await service.callback(state, browser, redirect, code, error)
    assert not fake.requests


@pytest.mark.asyncio
async def test_callback_success_and_replay(oauth_bundle, db_session):
    service, fake, _ = oauth_bundle
    state = state_from(await service.start(EMAIL, "browser"))
    result = await service.callback(state, "browser", CALLBACK, "valid-code")
    assert result["account_email"] == EMAIL
    assert result["google_subject"] == "fictional-stable-subject"
    assert result["live_verified"] is True
    assert "fictional-refresh" not in str(result) and "fictional-access" not in str(
        result
    )
    exchange = parse_qs(fake.requests[0].content.decode())
    assert exchange["code_verifier"] and exchange["code"] == ["valid-code"]
    with pytest.raises(ConnectionError, match="replayed"):
        await service.callback(state, "browser", CALLBACK, "valid-code")
    intent = await db_session.scalar(select(OAuthState))
    assert intent.consumed_at and intent.encrypted_verifier is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "exchange",
        "missing_refresh",
        "insufficient",
        "extra_write_scope",
        "malformed",
        "wrong_account",
        "unverified_email",
        "gmail_mismatch",
    ],
)
async def test_google_response_validation(oauth_bundle, failure):
    service, fake, _ = oauth_bundle
    state = state_from(await service.start(EMAIL, "browser"))
    if failure == "exchange":
        fake.fail = "/token"
    elif failure == "missing_refresh":
        fake.token.pop("refresh_token")
    elif failure == "insufficient":
        fake.token["scope"] = "openid email"
    elif failure == "extra_write_scope":
        fake.token["scope"] += " https://www.googleapis.com/auth/gmail.send"
    elif failure == "malformed":
        fake.token["expires_in"] = "bad"
    elif failure == "wrong_account":
        fake.identity["email"] = fake.gmail_email = "other@example.com"
    elif failure == "unverified_email":
        fake.identity["email_verified"] = False
    elif failure == "gmail_mismatch":
        fake.gmail_email = "other@example.com"
    with pytest.raises(ConnectionError) as caught:
        await service.callback(state, "browser", CALLBACK, "valid-code")
    assert "fictional" not in str(caught.value) and "secret" not in str(caught.value)
    assert (await service.status())["status"] == "disconnected"
    with pytest.raises(ConnectionError, match="replayed"):
        await service.callback(state, "browser", CALLBACK, "valid-code")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/callback",
        CALLBACK + "?next=evil",
        CALLBACK + "#fragment",
        "http://example.com/api/v1/integrations/gmail/oauth/callback",
        "https://user:pass@localhost/api/v1/integrations/gmail/oauth/callback",
    ],
)
def test_redirect_uri_settings_reject_arbitrary_urls(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, GMAIL_REDIRECT_URI=url)


@pytest.mark.asyncio
async def test_expected_account_config_cannot_be_overridden(oauth_bundle):
    service, _, _ = oauth_bundle
    service.settings.GMAIL_EXPECTED_EMAIL = "intended@example.com"
    with pytest.raises(ConnectionError, match="mismatch"):
        await service.start(EMAIL, "browser")


@pytest.mark.asyncio
async def test_new_intent_supersedes_old_callback(oauth_bundle):
    service, _, _ = oauth_bundle
    old = state_from(await service.start(EMAIL, "old-browser"))
    current = state_from(await service.start(EMAIL, "new-browser"))
    with pytest.raises(ConnectionError, match="superseded"):
        await service.callback(old, "old-browser", CALLBACK, "code")
    assert (await service.callback(current, "new-browser", CALLBACK, "code"))[
        "status"
    ] == "connected"
