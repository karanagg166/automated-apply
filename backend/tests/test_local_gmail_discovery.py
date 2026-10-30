"""Fictional Gmail fixtures exercise durable reads and concurrent stop fences."""

import base64
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail import job_alerts as alerts
from backend.app.models.job import Job
from backend.tests.phase4a_fakes import GoogleFixture
from backend.tests.test_phase54_mailboxes import configured, connect

LINK = "https://www.naukri.com/job-listings-python-developer-fixture-0-to-2-years-261026028027"


def message(identity="mail1", trusted=True):
    return {"id": identity, "labelIds": ["INBOX"], "payload": {
        "headers": [{"name": "From", "value": alerts.SENDER}, {"name": "Subject", "value": "New Python jobs"},
            {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@naukri.com; dmarc=" + ("pass" if trusted else "fail") + " header.from=naukri.com"}],
        "mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(
            (f'<a href="{LINK}">Python Developer</a><a href="https://tracking.example.org/x">Tracking</a>private body').encode()).decode()}}}


async def activate(session, settings, fake, oauth):
    mailbox, account, _ = await connect(session, settings, fake, oauth)
    await alerts.configure(session, settings, "1", alerts.AlertPolicy(expected_version=0,
        expected_generation=account["generation"], enabled=True))
    session.add(OwnerPreference(key="naukri_automation", value={"state": "RUNNING", "revision": 1, "policy": None}))
    await session.commit()
    return mailbox


@pytest.mark.parametrize("trusted", [True, False])
async def test_incremental_alert_cycle_deduplicates_and_authenticates_before_body(db_session, trusted):
    settings, fake, calls = configured(), GoogleFixture(), []
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "gmail.googleapis.com"
        if request.url.path.endswith("/messages"):
            assert request.url.params["q"].startswith("in:inbox from:naukrialerts@naukri.com after:")
            return httpx.Response(200, json={"messages": [{"id": "mail1"}, {"id": "mail2"}]})
        if not trusted:
            assert request.url.params["format"] == "metadata"
        return httpx.Response(200, json=message(request.url.path.rsplit("/", 1)[-1], trusted))

    async with fake.client() as oauth, httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        mailbox = await activate(db_session, settings, fake, oauth)

        def construct(session, settings):
            return type(mailbox)(session, settings, mailbox.google, client)

        first = await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        assert first["status"] == "observed"
        assert first["candidates_added"] == int(trusted)
        assert first["rejected_origin"] == (0 if trusted else 2)
        count = len(calls)
        second = await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        assert second["candidates_added"] == 0 and len(calls) == count + 1
    rows = list((await db_session.scalars(select(OwnerPreference).where(OwnerPreference.key.startswith("nau_alert:")))).all())
    assert len(rows) == int(trusted)
    if trusted:
        assert rows[0].value["posting_status"] == "unknown" and rows[0].value["state"] == "NEEDS_INPUT"
        assert len(rows[0].value["message_references"]) == 2
        assert "private body" not in json.dumps(rows[0].value)
    sync = await alerts.status(db_session, "1")
    assert sync["watermark"] > 0 and sync["last_check_at"]


@pytest.mark.parametrize("change", ["stop", "pause", "disconnect", "policy"])
async def test_authority_change_during_http_prevents_publication_and_cursor_advance(db_session, change):
    settings, fake = configured(), GoogleFixture()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    async def respond(request):
        assert request.url.path.endswith("/messages")
        async with factory() as session:
            if change in {"stop", "pause"}:
                row = await session.get(OwnerPreference, "naukri_automation")
                row.value = {**row.value, "state": "STOPPED" if change == "stop" else "PAUSED", "revision": 2}
            elif change == "disconnect":
                row = await session.get(OwnerPreference, "gm54_account:1")
                row.value = {**row.value, "generation": 2}
            else:
                row = await session.get(OwnerPreference, alerts.PREFIX + "1")
                row.value = {**row.value, "version": 2}
            await session.commit()
        return httpx.Response(200, json={"messages": [{"id": "mail1"}]})

    async with fake.client() as oauth, httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        mailbox = await activate(db_session, settings, fake, oauth)

        def construct(session, settings):
            return type(mailbox)(session, settings, mailbox.google, client)

        with pytest.raises(Exception, match="gmail_.*(?:authority_changed|account_changed)"):
            await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
    rows = list((await db_session.scalars(select(OwnerPreference).where(OwnerPreference.key.startswith("nau_alert:")))).all())
    assert not rows
    sync = await alerts.status(db_session, "1")
    assert not sync.get("watermark") and not sync.get("last_result")


def test_sender_authentication_does_not_accept_lookalike_domain_or_duplicate_headers():
    valid = message()
    assert alerts.authenticated_alert(valid)
    valid["payload"]["headers"][0]["value"] = "naukrialerts@naukri.com.attacker.example"
    assert not alerts.authenticated_alert(valid)
    valid = message()
    valid["payload"]["headers"].append(valid["payload"]["headers"][-1])
    assert not alerts.authenticated_alert(valid)


async def test_disabled_policy_never_uses_mailbox(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    def forbidden(*_):
        pytest.fail("Disabled discovery touched a mailbox")

    result = await alerts.poll(factory, configured(), mailbox_factory=forbidden)
    assert result["status"] == "disabled_or_paused"


async def test_existing_applied_requisition_is_audited_without_new_job_or_packet(db_session):
    existing = Job(title="Fictional original title", job_url=LINK, source_platform="naukri", status="applied")
    db_session.add(existing)
    await db_session.flush()
    await alerts.retain(db_session, "1", {"account_email": "first@example.org"}, message(), "fictional-received-at")
    candidate = await db_session.scalar(select(OwnerPreference).where(OwnerPreference.key.startswith("nau_alert:")))
    assert candidate.value["state"] == "ALREADY_APPLIED" and candidate.value["job_id"] == str(existing.id)
    assert len(list((await db_session.scalars(select(Job))).all())) == 1
    assert existing.title == "Fictional original title" and existing.status == "applied"


async def test_failed_page_preserves_committed_message_receipts_and_restarts_cursor(db_session):
    settings, fake, reads, fail = configured(), GoogleFixture(), [], [True]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    def respond(request):
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "mail1"}, {"id": "mail2"}], "nextPageToken": "next-fixture-page"})
        identity = request.url.path.rsplit("/", 1)[-1]
        reads.append(identity)
        if identity == "mail2" and fail[0]:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=message(identity))

    async with fake.client() as oauth, httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        mailbox = await activate(db_session, settings, fake, oauth)

        def construct(session, settings):
            return type(mailbox)(session, settings, mailbox.google, client)

        with pytest.raises(Exception, match="gmail_read_upstream_error"):
            await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        failed = await alerts.status(db_session, "1")
        assert not failed.get("watermark") and failed["error"]
        first_reads = reads.count("mail1")
        fail[0] = False
        result = await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        assert reads.count("mail1") == first_reads and result["candidates_added"] == 0
        # The upper boundary advances only after the final page, never page one.
        current = await alerts.status(db_session, "1")
        assert not current.get("watermark")


async def test_multi_job_alert_does_not_hold_owner_lock_over_per_link_queries(db_session):
    from sqlalchemy import event

    selectors = []

    def count_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selectors.append(statement)

    view = message()
    view["payload"]["body"]["data"] = base64.urlsafe_b64encode(" ".join(
        LINK.replace("261026028027", str(261026028000 + index)) for index in range(25)
    ).encode()).decode()
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        added, links = await alerts.retain(db_session, "1", {"account_email": "first@example.org"}, view, "fictional")
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
    assert added == links == 25
    assert len(selectors) <= 6
