"""Bounded fictional Gmail transports; never connects an owner account."""

import base64
import json
from datetime import timedelta
from email import message_from_bytes

import httpx
import pytest

from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.mailboxes import ACCOUNT, Consent, Mailboxes, Search
from backend.app.integrations.google_oauth import READ_DRAFT_SCOPES, GoogleOAuth
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import (
    CALLBACK,
    GoogleFixture,
    oauth_settings,
    state_from,
)


def configured(**values):
    return oauth_settings(GMAIL_LOCAL_ACCOUNTS_ENABLED=True, GMAIL_READ_BODY_REVIEWED=True,
        GMAIL_DRAFTS_ENABLED=True, GMAIL_LOCAL_ALLOWED_EMAILS=["first@example.org", "second@example.org"], **values)


async def connect(session, settings, fake, client, slot="1", email="first@example.org"):
    fake.token["scope"] = " ".join(sorted(READ_DRAFT_SCOPES))
    fake.identity.update(email=email, sub=email + "-subject")
    fake.gmail_email = email
    service = Mailboxes(session, settings, GoogleOAuth(settings, client))
    start = await service.start(slot, Consent(account_consent=True, read_and_draft_consent=True), "browser-" + slot)
    result = await service.callback(state_from(start), "browser-" + slot, CALLBACK, "code")
    return service, result, start


async def test_two_account_grants_are_exact_encrypted_and_browser_bound(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as client:
        service, first, start = await connect(db_session, settings, fake, client)
        assert not first["permissions"]["send"] and not first["permissions"]["monitoring"]
        assert "gmail.metadata" not in start["authorization_url"]
        with pytest.raises(ConnectionError, match="replayed"):
            await service.callback(state_from(start), "browser-1", CALLBACK, "code")
        second = await service.start("2", Consent(account_consent=True, read_and_draft_consent=True), "browser-2")
        with pytest.raises(ConnectionError, match="replayed"):
            await service.callback(state_from(second), "browser-1", CALLBACK, "code")
        with pytest.raises(ConnectionError, match="already_connected"):
            await service.callback(state_from(second), "browser-2", CALLBACK, "code")
        _, other, _ = await connect(db_session, settings, fake, client, "2", "second@example.org")
        assert other["account_email"] != first["account_email"]
        row = await db_session.get(OwnerPreference, ACCOUNT + "1")
        assert "fictional-refresh" not in json.dumps(row.value)
        with pytest.raises(ConnectionError, match="decryption"):
            TokenStore(settings).decrypt(row.value["refresh"], ACCOUNT + "2:refresh")


async def test_disable_and_consent_gates_precede_google_requests(db_session):
    service = Mailboxes(db_session, oauth_settings())
    with pytest.raises(ConnectionError, match="disabled"):
        await service.start("1", Consent(account_consent=True, read_and_draft_consent=True), "browser")
    service = Mailboxes(db_session, configured())
    with pytest.raises(ConnectionError, match="consent"):
        await service.start("1", Consent(account_consent=True, read_and_draft_consent=False), "browser")


async def test_unapproved_email_cannot_connect_or_reuse_saved_tokens(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as client:
        with pytest.raises(ConnectionError, match="not_authorized"):
            await connect(db_session, settings, fake, client, "1", "unselected@example.org")
        service, _, _ = await connect(db_session, settings, fake, client, "1", "first@example.org")
        restricted = settings.model_copy(update={"GMAIL_LOCAL_ALLOWED_EMAILS": ["second@example.org"]})
        service.settings = restricted
        with pytest.raises(ConnectionError, match="not_authorized"):
            await service.access("1")


async def test_inbox_selection_is_account_bound_and_body_is_not_persisted(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as oauth:
        service, _, _ = await connect(db_session, settings, fake, oauth)
        await connect(db_session, settings, fake, oauth, "2", "second@example.org")
        requests = []

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/messages"):
                assert request.url.params.get_list("labelIds") == ["INBOX"]
                assert int(request.url.params["maxResults"]) <= 5
                return httpx.Response(200, json={"messages": [{"id": "mail1"}]})
            return httpx.Response(200, json={"id": "mail1", "labelIds": ["INBOX"], "payload": {
                "headers": [{"name": "From", "value": "alerts@naukri.com"}, {"name": "Subject", "value": "Naukri jobs"}],
                "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b'private body job alert').decode()}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service.client = mailbox
            found = await service.search("1", Search())
            assert len(found["messages"]) == 1
            with pytest.raises(ConnectionError, match="selection"):
                await service.read("2", "mail1")
            result = await service.read("1", "mail1")
            assert result["body_stored"] is False and result["links_opened"] is False
            assert result["origin"]["authenticated_origin_verified"] is False
            assert len(requests) == 3


async def test_self_draft_is_real_endpoint_idempotent_and_checks_sent(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as oauth:
        service, account, _ = await connect(db_session, settings, fake, oauth)
        writes, marker = [], []

        def respond(request):
            if request.method == "POST":
                assert request.url.path.endswith("/drafts")
                writes.append(request)
                msg = message_from_bytes(base64.urlsafe_b64decode(json.loads(request.content)["message"]["raw"]))
                assert msg["From"] == msg["To"] == account["account_email"]
                marker.append(msg["Message-ID"])
                return httpx.Response(200, json={"id": "draft1"})
            if request.url.path.endswith("/messages"):
                assert request.url.params.get_list("labelIds") == ["SENT"]
                assert "rfc822msgid:" in request.url.params["q"]
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"id": "draft1", "message": {"labelIds": ["DRAFT"], "payload": {"headers": [
                {"name": "To", "value": account["account_email"]}, {"name": "Message-ID", "value": marker[0]}]}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service.client = mailbox
            first = await service.self_test_draft("1", account["generation"])
            again = await service.self_test_draft("1", account["generation"])
            assert first["draft_exists"] and again["sent_search_empty"]
            assert len(writes) == 1


async def test_ambiguous_draft_dispatch_is_never_repeated(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as oauth:
        service, account, _ = await connect(db_session, settings, fake, oauth)
        writes = []
        def respond(request):
            if request.method == "POST":
                writes.append(request)
                raise httpx.ReadTimeout("fictional acceptance ambiguity")
            return httpx.Response(200, json={"drafts": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service.client = mailbox
            with pytest.raises(ConnectionError, match="unconfirmed"):
                await service.self_test_draft("1", account["generation"])
            with pytest.raises(ConnectionError, match="outcome_unknown"):
                await service.self_test_draft("1", account["generation"])
            assert len(writes) == 1


async def test_refresh_cannot_switch_identity_and_disconnect_scrubs_only_one_account(db_session):
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as oauth:
        service, _, _ = await connect(db_session, settings, fake, oauth)
        await connect(db_session, settings, fake, oauth, "2", "second@example.org")
        row = await db_session.get(OwnerPreference, ACCOUNT + "1")
        row.value = {**row.value, "expires_at": (now() - timedelta(seconds=1)).isoformat()}
        await db_session.commit()
        with pytest.raises(ConnectionError, match="reauthorization"):
            await service.access("1")
        assert (await service.status("1"))["status"] == "reauthorization_required"
        await service.disconnect("1")
        assert "refresh" not in (await db_session.get(OwnerPreference, ACCOUNT + "1")).value
        assert (await service.status("2"))["status"] == "connected"


async def test_reviewed_generic_draft_verifies_exact_content_and_rejects_later_edit(db_session):
    from uuid import uuid4

    from backend.app.integrations.gmail.mailboxes import ReviewedDraft, draft_hash
    settings, fake = configured(), GoogleFixture()
    async with fake.client() as oauth:
        service, account, _ = await connect(db_session, settings, fake, oauth)
        content = dict(recipient="recipient@example.org", subject="Reviewed local draft", body="Owner-provided text only")
        data = ReviewedDraft(expected_generation=account["generation"], request_id=uuid4(), owner_reviewed=True,
            content_hash=draft_hash(**content), **content)
        saved, writes = [], []
        def respond(request):
            if request.method == "POST":
                writes.append(request)
                saved.append(message_from_bytes(base64.urlsafe_b64decode(json.loads(request.content)["message"]["raw"])))
                return httpx.Response(200, json={"id": "reviewed1"})
            message = saved[0]
            return httpx.Response(200, json={"id": "reviewed1", "message": {"labelIds": ["DRAFT"], "payload": {
                "mimeType": "text/plain", "headers": [{"name": key, "value": message[key]} for key in ["From", "To", "Subject", "Message-ID"]],
                "body": {"data": base64.urlsafe_b64encode(message.get_payload(decode=True)).decode()}}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service.client = mailbox
            assert (await service.create_draft("1", data))["content_verified"]
            assert (await service.create_draft("1", data))["draft_exists"]
            assert len(writes) == 1
            with pytest.raises(ConnectionError, match="exact_draft_review"):
                await service.create_draft("1", data.model_copy(update={"body": "Changed without review"}))


async def test_cross_account_alert_dedup_keeps_origins_and_unknown_facts(db_session):
    from backend.app.integrations.gmail.alert_candidates import record_candidates
    url = "https://www.naukri.com/job-listings-fictional-backend-fictional-123456789012"
    with pytest.raises(ConnectionError, match="authorization"):
        await record_candidates(db_session, source="gmail", account="1", message_id="a", sender="alerts@naukri.com", links=[url])
    first = await record_candidates(db_session, source="gmail", account="1", message_id="a", sender="alerts@naukri.com", links=[url], monitoring_authorized=True)
    second = await record_candidates(db_session, source="gmail", account="2", message_id="b", sender="alerts@naukri.com", links=[url + "?tracking=discard", "https://attacker.example/redirect"], monitoring_authorized=True)
    assert first[0]["requisition"] == second[0]["requisition"]
    assert len(second) == 1 and len(second[0]["sources"]) == 2
    assert second[0]["state"] == "NEEDS_FACTUAL_AND_ORIGIN_REVIEW" and second[0]["origin_authenticated"] is False
