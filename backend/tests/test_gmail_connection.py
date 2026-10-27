"""Refresh, revoked credentials, disconnection, REST identity and no token exposure."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from backend.app.api.v1.integrations import connection_service
from backend.app.integrations.token_store import ConnectionError
from backend.app.main import app
from backend.app.models.connected_account import ConnectedAccount
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import CALLBACK, EMAIL, state_from


async def connect(service):
    state = state_from(await service.start(EMAIL, "browser"))
    return await service.callback(state, "browser", CALLBACK, "code")


@pytest.mark.asyncio
async def test_cached_token_then_refresh(oauth_bundle, db_session):
    service, fake, _ = oauth_bundle
    await connect(service)
    assert await service.access_token() == "fictional-access"
    assert len([r for r in fake.requests if r.url.path == "/token"]) == 1
    account = await db_session.scalar(select(ConnectedAccount))
    assert "fictional-refresh" not in account.encrypted_refresh_token
    account.token_expires_at = now() - timedelta(seconds=1)
    await db_session.commit()
    fake.token["access_token"] = "fictional-refreshed-access"
    assert await service.access_token() == "fictional-refreshed-access"
    assert (await service.status())["last_refresh_at"]
    assert (
        b"grant_type=refresh_token"
        in [r for r in fake.requests if r.url.path == "/token"][-1].content
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["revoked", "changed_scopes", "account_swapped"])
async def test_refresh_failure_requires_reauthorization(
    oauth_bundle, db_session, failure
):
    service, fake, _ = oauth_bundle
    await connect(service)
    account = await db_session.scalar(select(ConnectedAccount))
    account.token_expires_at = now() - timedelta(seconds=1)
    await db_session.commit()
    if failure == "revoked":
        fake.fail = "/token"
    elif failure == "changed_scopes":
        fake.token["scope"] = "openid email"
    else:
        fake.identity["sub"] = "other-stable-subject"
    with pytest.raises(ConnectionError, match="reauthorization"):
        await service.access_token()
    assert (await service.status())["status"] == "reauthorization_required"


@pytest.mark.asyncio
async def test_disconnect_reconnect_and_no_silent_overwrite(oauth_bundle, db_session):
    service, fake, _ = oauth_bundle
    old = await connect(service)
    with pytest.raises(ConnectionError, match="disconnect"):
        await service.start("different@example.com", "browser")
    result = await service.disconnect()
    assert result["revocation"] == "revoked"
    account = await db_session.scalar(select(ConnectedAccount))
    assert (
        account.encrypted_refresh_token is None
        and account.encrypted_access_token is None
    )
    assert (await connect(service))["id"] == old["id"]
    assert any(r.url.path == "/revoke" for r in fake.requests)


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_callback(oauth_bundle):
    service, _, _ = oauth_bundle
    state = state_from(await service.start(EMAIL, "browser"))
    await service.disconnect()
    with pytest.raises(ConnectionError):
        await service.callback(state, "browser", CALLBACK, "code")


@pytest.mark.asyncio
async def test_failed_remote_revocation_still_clears_local_secrets(
    oauth_bundle, db_session
):
    service, fake, _ = oauth_bundle
    await connect(service)
    fake.fail = "/revoke"
    result = await service.disconnect()
    assert "unconfirmed" in result["revocation"]
    assert (
        await db_session.scalar(select(ConnectedAccount))
    ).encrypted_refresh_token is None


@pytest.mark.asyncio
async def test_integration_endpoints_auth_and_safe_status(async_client, phase2_auth):
    for path in (
        "/api/v1/integrations",
        "/api/v1/integrations/gmail/status",
        "/api/v1/integrations/mcp/status",
    ):
        assert (await async_client.get(path)).status_code == 401
        response = await async_client.get(path, headers=phase2_auth)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert (
            "refresh_token" not in response.text
            and "client_secret" not in response.text
        )


@pytest.mark.asyncio
async def test_browser_oauth_callback_without_bearer(oauth_bundle, phase2_auth):
    service, _, _ = oauth_bundle
    app.dependency_overrides[connection_service] = lambda: service
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://localhost"
        ) as client:
            start = await client.post(
                "/api/v1/integrations/gmail/connect/start",
                headers=phase2_auth,
                json={"expected_email": EMAIL},
            )
            assert start.status_code == 200, start.text
            cookie = start.headers["set-cookie"]
            assert "HttpOnly" in cookie and "SameSite=lax" in cookie
            response = await client.get(
                CALLBACK, params={"state": state_from(start.json()), "code": "code"}
            )
            assert response.status_code == 200, response.text
            assert "fictional-refresh" not in response.text
            assert response.headers["referrer-policy"] == "no-referrer"
    finally:
        app.dependency_overrides.pop(connection_service)


@pytest.mark.asyncio
async def test_no_sending_or_mailbox_write_routes(async_client, phase2_auth):
    assert (
        await async_client.post("/api/v1/outreach/send", headers=phase2_auth)
    ).status_code == 404
    assert (
        await async_client.post("/api/v1/integrations/gmail/send", headers=phase2_auth)
    ).status_code == 404


@pytest.mark.asyncio
async def test_revoked_cached_token_detected_by_verify(oauth_bundle):
    service, fake, _ = oauth_bundle
    await connect(service)
    fake.fail = "/v1/userinfo"
    with pytest.raises(ConnectionError, match="reauthorization"):
        await service.verify()
    assert (await service.status())["status"] == "reauthorization_required"


def test_oauth_query_log_redaction():
    import logging

    from backend.app.integrations.logging import OAuthAccessLogFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        (
            "127.0.0.1",
            "GET",
            "/api/v1/integrations/gmail/oauth/callback?code=secret-code&state=secret-state",
            "1.1",
            200,
        ),
        None,
    )
    OAuthAccessLogFilter().filter(record)
    assert (
        "secret-code" not in record.getMessage()
        and "secret-state" not in record.getMessage()
    )


@pytest.mark.asyncio
async def test_registry_does_not_claim_unimplemented_or_live_connectors(
    async_client, phase2_auth
):
    result = (
        await async_client.get("/api/v1/integrations", headers=phase2_auth)
    ).json()
    platforms = {item["platform"]: item for item in result["connectors"]}
    assert set(platforms) == {
        "linkedin",
        "naukri",
        "instahyre",
        "work_at_a_startup",
        "wellfound",
        "internshala",
        "greenhouse",
        "apollo",
        "signalhire",
        "gmail",
    }
    assert not any(item["live_verified"] for item in platforms.values())
    assert platforms["internshala"]["capabilities"]["discover_jobs"] == "manual_only"
    assert platforms["linkedin"]["capabilities"]["discover_jobs"] == "manual_only"
    assert platforms["signalhire"]["capabilities"]["discover_people"] == "unsupported"
    assert platforms["gmail"]["capabilities"]["send_email"] == "unsupported"
    assert platforms["gmail"]["capabilities"]["read_job_alerts"] == "unsupported"


def test_legacy_plaintext_oauth_setup_is_retired(capsys):
    from backend.scripts.setup_gmail_oauth import main

    assert main() == 2
    assert "connect/start" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_legacy_scope_reporting_includes_metadata_and_disconnected_permissions(oauth_bundle):
    from backend.app.integrations.google_oauth import SEND_SCOPES
    service, fake, _ = oauth_bundle
    await connect(service)
    fake.token["scope"] = " ".join(sorted(SEND_SCOPES))
    state = state_from(await service.start(EMAIL, "browser", send=True))
    result = await service.callback(state, "browser", CALLBACK, "code")
    assert result["permissions"]["read_metadata"] and result["permissions"]["send"]
    await service.disconnect()
    status = await service.status()
    assert status["permissions"]["send"] is False and status["permissions"]["read_metadata"] is False
