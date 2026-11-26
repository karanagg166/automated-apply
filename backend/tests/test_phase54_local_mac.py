"""Fictional local adapter boundaries. No Mail app or real Chrome is invoked."""

from uuid import uuid4

import pytest

from backend.app.integrations.token_store import ConnectionError
from backend.app.local_agent.apple_mail import AppleMail, Draft
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import oauth_settings


def mail_settings(**values):
    return oauth_settings(APPLE_MAIL_ENABLED=True, APPLE_MAIL_ACCOUNT_POLICIES={"account1": {
        "address": "owner@example.org", "inbox_mailbox": "INBOX", "drafts_mailbox": "Drafts",
        "read_authorized": True, "draft_authorized": True, "senders": ["alerts@naukri.com"]}}, **values)


async def test_mail_account_allowlist_separate_permissions_and_selected_reads(db_session):
    calls = []
    async def run(request):
        calls.append(request)
        return {"messages": [{"id": 1, "sender": "alerts@naukri.com.attacker.example", "subject": "spoof"},
            {"id": 2, "sender": "Naukri <alerts@naukri.com>", "subject": "job alert"}]}
    service = AppleMail(db_session, mail_settings(), run)
    with pytest.raises(ConnectionError, match="not_allowed"):
        await service.search("another")
    found = await service.search("account1")
    assert [m["id"] for m in found["messages"]] == [2]
    with pytest.raises(ConnectionError, match="selection"):
        await service.read("account1", 1)
    assert len(calls) == 1


async def test_mail_read_extracts_without_opening_or_storing_private_body(db_session):
    async def run(request):
        value = {"id": 2, "sender": "Naukri <alerts@naukri.com>", "subject": "Job alert", "received_at": now().isoformat()}
        return {"messages": [value]} if request["action"] == "search" else {**value, "body": "private job alert text"}
    service = AppleMail(db_session, mail_settings(), run)
    await service.search("account1")
    result = await service.read("account1", 2)
    assert "body" not in result and result["body_stored"] is False and result["links_opened"] is False


async def test_mail_draft_ambiguity_only_reconciles_on_retry(db_session):
    calls = []
    async def run(request):
        calls.append(request["action"])
        raise ConnectionError("apple_mail_operation_unconfirmed")
    service = AppleMail(db_session, mail_settings(), run)
    data = Draft(request_id=uuid4(), recipient="owner@example.org", subject="Unsent test", body="Fictional local draft", owner_reviewed=True)
    with pytest.raises(ConnectionError):
        await service.draft("account1", data)
    with pytest.raises(ConnectionError):
        await service.draft("account1", data)
    assert calls == ["draft", "verify_draft"]


async def test_mail_defaults_never_start_scripting(db_session):
    async def denied(request):
        pytest.fail("Disabled adapter invoked Apple Mail")
    service = AppleMail(db_session, oauth_settings(), denied)
    assert (await service.accounts())["enabled"] is False
    with pytest.raises(ConnectionError, match="disabled"):
        await service.search("account1")


