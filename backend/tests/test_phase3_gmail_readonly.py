"""Fictional independently authorized Gmail accounts; network writes are forbidden."""

import base64
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.gmail.read_client import GmailReadClient, content_evidence
from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
from backend.app.integrations.google_oauth import READ_SCOPES, GoogleOAuth
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.connected_account import GmailReadAccount
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import (
    CALLBACK,
    GoogleFixture,
    oauth_settings,
    state_from,
)


async def connect(session, settings, fake, client, email, *, body=False):
    fake.identity["email"] = fake.gmail_email = email
    fake.identity["sub"] = email + "-subject"
    fake.token["access_token"] = email + "-access"
    fake.token["refresh_token"] = email + "-refresh"
    if body:
        fake.token["scope"] = " ".join(sorted(READ_SCOPES))
    service = ConnectionService(
        session, settings, GoogleOAuth(settings, client), read_only=True
    )
    result = await service.start(email, "browser", read_body=body)
    assert (
        "gmail.send" not in result["authorization_url"]
        and "gmail.compose" not in result["authorization_url"]
    )
    result = await service.callback(state_from(result), "browser", CALLBACK, "code")
    return UUID(result["id"])


async def test_multi_account_identity_tokens_disconnect_and_pending_state_isolation(
    db_session,
):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        first = await connect(db_session, settings, fake, client, "first@example.com")
        second = await connect(db_session, settings, fake, client, "second@example.com")
        for account_id, expected in ((first, "first"), (second, "second")):
            service = ConnectionService(
                db_session,
                settings,
                GoogleOAuth(settings, client),
                read_only=True,
                account_id=account_id,
            )
            assert await service.access_token() == expected + "@example.com-access"
        read = GmailReadService(
            db_session, settings, google=GoogleOAuth(settings, client)
        )
        assert len(await read.accounts()) == 2
        pending = ConnectionService(
            db_session, settings, GoogleOAuth(settings, client), read_only=True
        )
        intent = await pending.start("third@example.com", "browser")
        await read.disconnect(first)
        fake.identity["email"] = fake.gmail_email = "third@example.com"
        fake.identity["sub"] = "third-subject"
        await pending.callback(state_from(intent), "browser", CALLBACK, "code")
        assert (await read.status(second))["permissions"] == {
            "read_metadata": True,
            "read_body": False,
            "send": False,
            "modify": False,
        }
        assert (await read.status(first))["status"] == "disconnected"
        accounts = (await db_session.scalars(select(GmailReadAccount))).all()
        tokens = [
            a.encrypted_refresh_token for a in accounts if a.encrypted_refresh_token
        ]
        with pytest.raises(ConnectionError):
            TokenStore(settings).decrypt(tokens[0], str(first) + ":refresh")


async def test_read_body_scope_requires_review_and_never_accepts_writes(db_session):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        service = ConnectionService(
            db_session, settings, GoogleOAuth(settings, client), read_only=True
        )
        for kwargs in ({"send": True}, {"compose": True}, {"read_body": True}):
            with pytest.raises(ConnectionError):
                await service.start("first@example.com", "browser", **kwargs)
        fake.token["scope"] += " https://www.googleapis.com/auth/gmail.modify"
        with pytest.raises(ConnectionError, match="unexpected_or_insufficient_scopes"):
            await connect(db_session, settings, fake, client, "first@example.com")


async def test_selected_metadata_sync_pagination_duplicate_restart_and_account_isolation(
    db_session,
):
    settings, fake = oauth_settings(GMAIL_READ_SYNC_ENABLED=True), GoogleFixture()
    async with fake.client() as oauth_client:
        first = await connect(
            db_session, settings, fake, oauth_client, "first@example.com"
        )
        second = await connect(
            db_session, settings, fake, oauth_client, "second@example.com"
        )
        calls = []

        def respond(request):
            calls.append(request)
            assert request.method == "GET" and "q" not in request.url.params
            assert request.headers["Authorization"].endswith("first@example.com-access")
            if request.url.path.endswith("/messages"):
                return httpx.Response(
                    200,
                    json={
                        "messages": [{"id": "m1"}],
                        **(
                            {"nextPageToken": "next"}
                            if not request.url.params.get("pageToken")
                            else {}
                        ),
                    },
                )
            assert request.url.params["format"] == "metadata"
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "threadId": "t1",
                    "internalDate": str(
                        int((now() - timedelta(hours=1)).timestamp() * 1000)
                    ),
                    "labelIds": ["Label_jobs"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Jobs <jobs@example.com>"},
                            {"name": "Subject", "value": "Job alert for backend roles"},
                        ]
                    },
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as gmail_client:
            service = GmailReadService(
                db_session,
                settings,
                google=GoogleOAuth(settings, oauth_client),
                client=gmail_client,
            )
            policy = ReadPolicy(
                expected_version=0,
                enabled=True,
                sender_allowlist=["jobs@example.com"],
                label_allowlist=["Label_jobs"],
            )
            await service.configure(first, policy)
            assert (await service.sync(first))["sync"]["status"] == "partial"
            service = GmailReadService(
                db_session,
                settings,
                google=GoogleOAuth(settings, oauth_client),
                client=gmail_client,
            )
            assert (await service.sync(first))["sync"]["status"] == "completed"
            evidence = await service.evidence(first)
            assert len(evidence) == 1 and not evidence[0]["submission_confirmed"]
            assert not await service.evidence(second)
            assert "Job alert" not in str(evidence) and "jobs@example.com" not in str(
                evidence
            )
            assert len([r for r in calls if "/messages/m1" in r.url.path]) == 1
            with pytest.raises(ConnectionError, match="selection"):
                await service.sync(second)
            await service.disconnect(first)
            assert not await service.evidence(first)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled": True},
        {"enabled": True, "sender_allowlist": ["jobs@example.com"]},
        {"enabled": True, "label_allowlist": ["INBOX"]},
        {"enabled": True, "label_allowlist": ["Label_jobs"], "query_allowlist": "jobs"},
        {"read_body": True},
        {"backfill_days": 31},
        {"max_pages": 4},
    ],
)
def test_read_selection_fails_closed(kwargs):
    with pytest.raises(ValidationError):
        ReadPolicy(expected_version=0, **kwargs)


def test_mime_sanitizes_html_limits_links_and_never_confirms_submission():
    html = '<script>interview</script><a href="https://example.com/jobs/1?token=private">job opening</a><a href="javascript:alert(1)">bad</a><a href="http://127.0.0.1/">bad</a>'
    result = content_evidence(
        {
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()},
        }
    )
    assert result["links"] == ["https://example.com/jobs/1"]
    assert (
        result["signals"] == ["possible_job_lead"]
        and result["submission_confirmed"] is False
    )
    with pytest.raises(ConnectionError):
        content_evidence({"mimeType": "text/plain", "body": {"data": "invalid!"}})


async def test_client_denies_arbitrary_paths_and_byte_caps():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: calls.append(r) or httpx.Response(200, content=b"x" * 1048577)
        )
    ) as client:
        reader = GmailReadClient("fictional-access", client)
        with pytest.raises(ConnectionError, match="operation_denied"):
            await reader.get("messages/send", {})
        assert not calls
        with pytest.raises(ConnectionError, match="response_limit"):
            await reader.messages(labels=["Label_jobs"])


async def test_new_account_apis_auth_before_validation(async_client, phase2_auth):
    path = "/api/v1/integrations/gmail/accounts"
    assert (await async_client.get(path)).status_code == 401
    assert (
        await async_client.post(path + "/connect/start", json={})
    ).status_code == 401
    response = await async_client.get(path, headers=phase2_auth)
    assert response.status_code == 200 and response.json()["accounts"] == []
    assert response.headers["cache-control"] == "no-store"


async def test_explicit_body_sync_and_reviewed_import_deduplicate_without_cross_account_data(
    db_session,
):
    from backend.app.integrations.gmail.read_service import LeadImport
    from backend.app.models.job import Job

    settings, fake = (
        oauth_settings(GMAIL_READ_SYNC_ENABLED=True, GMAIL_READ_BODY_REVIEWED=True),
        GoogleFixture(),
    )
    async with fake.client() as oauth_client:
        first = await connect(
            db_session, settings, fake, oauth_client, "first@example.com", body=True
        )
        second = await connect(
            db_session, settings, fake, oauth_client, "second@example.com", body=True
        )
        calls = []

        def respond(request):
            calls.append(request)
            assert request.method == "GET"
            if request.url.path.endswith("/messages"):
                assert "from:jobs@example.com" in request.url.params["q"]
                return httpx.Response(
                    200, json={"messages": [{"id": "body1"}, {"id": "body2"}]}
                )
            message_id = request.url.path.rsplit("/", 1)[-1]
            payload = {
                "id": message_id,
                "threadId": "one-thread",
                "internalDate": str(
                    int((now() - timedelta(hours=1)).timestamp() * 1000)
                ),
                "payload": {
                    "headers": [
                        {"name": "From", "value": "jobs@example.com"},
                        {"name": "Subject", "value": "Job opening"},
                    ]
                },
            }
            if request.url.params["format"] == "full":
                payload["payload"] = {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b'<p>Job opening</p><a href="https://fictional-employer.example/jobs/engineer?tracking=private">Engineer</a>'
                        ).decode()
                    },
                }
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = GmailReadService(
                db_session,
                settings,
                google=GoogleOAuth(settings, oauth_client),
                client=client,
            )
            await service.configure(
                first,
                ReadPolicy(
                    expected_version=0,
                    enabled=True,
                    read_body=True,
                    body_purpose="Read the actual job link omitted from the headers",
                    sender_allowlist=["jobs@example.com"],
                ),
            )
            await service.sync(first)
            leads = await service.leads(first)
            assert len(leads) == 1 and len(leads[0]["evidence_ids"]) == 2
            evidence_id = leads[0]["evidence_ids"][0]
            data = LeadImport(
                job_url=leads[0]["url"],
                title="Fictional Engineer",
                company_name="Fictional Employer",
                company_domain="fictional-employer.example",
                reviewed_job_evidence=True,
            )
            with pytest.raises(ConnectionError, match="evidence_not_found"):
                await service.import_lead(second, evidence_id, data)
            first_import = await service.import_lead(first, evidence_id, data)
            second_import = await service.import_lead(first, evidence_id, data)
            assert (
                first_import.inserted_count == 1 and second_import.inserted_count == 0
            )
            assert first_import.job_ids == second_import.job_ids
            assert len((await db_session.scalars(select(Job))).all()) == 1
            assert not await service.leads(second)
            assert all(r.method == "GET" for r in calls)


async def test_account_specific_expired_token_refresh(db_session):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        first = await connect(db_session, settings, fake, client, "first@example.com")
        second = await connect(db_session, settings, fake, client, "second@example.com")
        row = await db_session.get(GmailReadAccount, first)
        row.token_expires_at = now() - timedelta(seconds=1)
        await db_session.commit()
        fake.identity["email"] = fake.gmail_email = "first@example.com"
        fake.identity["sub"] = "first@example.com-subject"
        fake.token["access_token"] = "refreshed-first"
        fake.token["refresh_token"] = "rotated-first"
        service = ConnectionService(
            db_session,
            settings,
            GoogleOAuth(settings, client),
            read_only=True,
            account_id=first,
        )
        assert await service.access_token() == "refreshed-first"
        other = ConnectionService(
            db_session,
            settings,
            GoogleOAuth(settings, client),
            read_only=True,
            account_id=second,
        )
        assert await other.access_token() == "second@example.com-access"
        assert (await other.status())["last_refresh_at"] is None


async def test_sync_lease_blocks_duplicate_dispatch_and_policy_changes_abort_persistence(
    db_session,
):
    settings, fake = oauth_settings(GMAIL_READ_SYNC_ENABLED=True), GoogleFixture()
    async with fake.client() as oauth_client:
        account_id = await connect(
            db_session, settings, fake, oauth_client, "first@example.com"
        )
        service = None
        calls = []

        async def respond(request):
            calls.append(request)
            assert service is not None
            with pytest.raises(ConnectionError, match="already_running"):
                await service.sync(account_id)
            # Simulate an owner changing the selection while the GET was in flight.
            await service.configure(
                account_id,
                ReadPolicy(
                    expected_version=1, enabled=False, label_allowlist=["Label_jobs"]
                ),
            )
            return httpx.Response(200, json={"messages": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = GmailReadService(
                db_session,
                settings,
                google=GoogleOAuth(settings, oauth_client),
                client=client,
            )
            await service.configure(
                account_id,
                ReadPolicy(
                    expected_version=0, enabled=True, label_allowlist=["Label_jobs"]
                ),
            )
            with pytest.raises(ConnectionError, match="selection_changed"):
                await service.sync(account_id)
            assert len(calls) == 1 and not await service.evidence(account_id)
            assert (await service.status(account_id))["sync"]["status"] == "disabled"


async def test_reauthorization_preserves_account_selection_and_checkpoint(db_session):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        account_id = await connect(db_session, settings, fake, client, "first@example.com")
        service = GmailReadService(db_session, settings, google=GoogleOAuth(settings, client))
        await service.configure(account_id, ReadPolicy(expected_version=0, enabled=True, label_allowlist=["Label_jobs"]))
        policy = await service.policy_row(account_id)
        checkpoint = (now()-timedelta(hours=1)).isoformat()
        policy.value = {**policy.value, "checkpoint": checkpoint}
        account = await db_session.get(GmailReadAccount, account_id)
        account.status = "reauthorization_required"
        account.encrypted_access_token = None
        await db_session.commit()
        assert await connect(db_session, settings, fake, client, "first@example.com") == account_id
        status = await service.status(account_id)
        assert status["status"] == "connected" and status["sync"]["checkpoint"] == checkpoint
        assert status["sync"]["policy"]["enabled"] is True and status["permissions"]["send"] is False
