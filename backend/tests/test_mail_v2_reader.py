"""Phase 6A READ-ONLY mail reader: IMAP (EXAMINE + BODY.PEEK) -> Gmail API readonly -> Mail.app JXA
fallback, auto email-OTP, recruiter-reply / interview alerts and job-alert ingestion."""

from __future__ import annotations

import base64
import imaplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import httpx
import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.reader import (
    GmailApiReadClient,
    ImapReadClient,
    MailAppReadClient,
    MailEventStore,
    MailReadError,
    MailReadService,
    clean_link,
    extract_otp,
)

NOW = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
IMAP_CONFIG = MailConfig(imap_email="owner@example.com", imap_password="TEST_FAKE_TOKEN_ONLY")


def rfc822(sender, subject, body, *, minutes_ago=1, message_id=None, html=False):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, "owner@example.com", subject
    message["Date"] = format_datetime(NOW - timedelta(minutes=minutes_ago))
    message["Message-ID"] = message_id or f"<{abs(hash((sender, subject)))}@example.com>"
    message.set_content(body, subtype="html" if html else "plain")
    return bytes(message)


class FakeIMAP:
    def __init__(self, messages, *, fail=None):
        self.messages = messages
        self.fail = fail
        self.calls = []

    def __call__(self, host, port):
        self.calls.append(("connect", host, port))
        if self.fail:
            raise OSError(self.fail)
        return self

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"3"]

    def search(self, charset, *criteria):
        self.calls.append(("search", criteria))
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]

    def fetch(self, number, spec):
        self.calls.append(("fetch", number, spec))
        return "OK", [(b"1 (BODY[] {10}", self.messages[int(number) - 1])]

    def logout(self):
        self.calls.append(("logout",))

    # Anything that could write must never be called:
    def store(self, *args):  # pragma: no cover - asserted absent
        raise AssertionError("imap.store must never be called")

    def append(self, *args):  # pragma: no cover
        raise AssertionError("imap.append must never be called by the reader")


def service(imap=None, **kw):
    config = kw.pop("config", IMAP_CONFIG)
    reader = MailReadService(config, imap=ImapReadClient(config, factory=imap) if imap else None,
                             clock=lambda: NOW, **kw)
    if imap is None:
        reader.imap = ImapReadClient(MailConfig(), factory=FakeIMAP([]))  # unconfigured
    return reader


# --- primitives -------------------------------------------------------------------------------
@pytest.mark.parametrize("text,code", [
    ("Your OTP is 482913. It is valid for 10 minutes.", "482913"),
    ("Use verification code 7391 to sign in", "7391"),
    ("482913 is your one-time password for Naukri", "482913"),
    ("Call +91 98450 12345 for help. Your login code is 55120.", "55120"),
    ("Posted in 2026, salary 1200000", None),
    ("Welcome to Naukri! No code here.", None),
])
def test_extract_otp(text, code):
    assert extract_otp(text) == code


def test_clean_link_drops_tracking_tokens():
    assert clean_link("https://www.naukri.com/job-listings-x-123?src=alert&token=abc#f") == \
        "https://www.naukri.com/job-listings-x-123"


# --- tier 1: IMAP is EXAMINE + PEEK only ---------------------------------------------------------
async def test_imap_reads_with_examine_and_peek_only():
    fake = FakeIMAP([rfc822("Naukri <info@naukri.com>", "Your OTP for login", "Your OTP is 482913")])
    reader = service(fake)
    messages = await reader.recent(NOW - timedelta(days=1))
    assert messages[0].sender_domain == "naukri.com" and "482913" in messages[0].body
    assert ("select", '"INBOX"', True) in fake.calls
    assert all(call[2] == "(BODY.PEEK[])" for call in fake.calls if call[0] == "fetch")
    assert {c[0] for c in fake.calls} <= {"connect", "login", "select", "search", "fetch", "logout"}
    assert reader.last_tier == "imap"


async def test_fetch_recent_otp_matches_portal_sender_and_window():
    fake = FakeIMAP([
        rfc822("Naukri <info@naukri.com>", "Your OTP", "Your OTP is 111111", minutes_ago=30),  # too old
        rfc822("Evil <otp@naukri.com.evil.io>", "Your OTP", "Your OTP is 222222"),            # spoofed domain
        rfc822("Instahyre <noreply@instahyre.com>", "Verify", "Your verification code is 333333"),
        rfc822("Naukri <info@naukri.com>", "OTP for login", "Your OTP is 482913", minutes_ago=1),
    ])
    reader = service(fake)
    assert await reader.fetch_recent_otp("naukri", NOW - timedelta(minutes=3)) == "482913"
    assert await reader.fetch_recent_otp("instahyre", NOW - timedelta(minutes=3)) == "333333"
    assert await reader.fetch_recent_otp("wellfound", NOW - timedelta(minutes=3)) is None
    assert await reader.fetch_recent_otp("unknown_portal") is None


async def test_magic_link_only_from_the_portal_domain():
    fake = FakeIMAP([rfc822("Wellfound <hello@wellfound.com>", "Sign in to Wellfound",
                            "Click https://wellfound.com/login/magic?token=TEST_FAKE_TOKEN_ONLY to sign in")])
    link = await service(fake).fetch_recent_otp("wellfound", NOW - timedelta(minutes=3), want_link=True)
    assert link is not None and link.startswith("https://wellfound.com/login/magic")


# --- fallback chain ------------------------------------------------------------------------------------
def gmail_api(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET" and request.url.host == "gmail.googleapis.com"
    if request.url.path.endswith("/messages"):
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    body = base64.urlsafe_b64encode(b"Your OTP is 654321").decode().rstrip("=")
    return httpx.Response(200, json={"id": "m1", "internalDate": str(int(NOW.timestamp() * 1000)), "payload": {
        "headers": [{"name": "From", "value": "Naukri <info@naukri.com>"}, {"name": "Subject", "value": "OTP"},
                    {"name": "Message-ID", "value": "<gm1@naukri.com>"}],
        "mimeType": "text/plain", "body": {"data": body}}})


async def test_imap_failure_falls_back_to_gmail_api_readonly():
    async def token():
        return "TEST_FAKE_TOKEN_ONLY"

    async with httpx.AsyncClient(transport=httpx.MockTransport(gmail_api)) as client:
        reader = service(FakeIMAP([], fail="network down"), gmail_api=GmailApiReadClient(token, client=client))
        assert await reader.fetch_recent_otp("naukri", NOW - timedelta(minutes=3)) == "654321"
    assert reader.last_tier == "gmail_api" and reader.last_errors == ["imap:imap_oserror"]


async def test_gmail_api_failure_falls_back_to_mail_app_reader():
    requests = []

    async def runner(request):
        requests.append(request)
        return {"ok": True, "messages": [{"message_id": "<ma1@instahyre.com>", "sender": "Instahyre <a@instahyre.com>",
                                          "subject": "Your login code", "received_ms": NOW.timestamp() * 1000,
                                          "body": "Your code is 909090"}]}

    async def broken_token():
        return None

    reader = service(FakeIMAP([], fail="down"), gmail_api=GmailApiReadClient(broken_token),
                     mail_app=MailAppReadClient(IMAP_CONFIG, runner=runner, available=True))
    assert await reader.fetch_recent_otp("instahyre", NOW - timedelta(minutes=3)) == "909090"
    assert requests[0]["action"] == "read_recent" and reader.last_tier == "mail_app"
    assert reader.last_errors == ["imap:imap_oserror", "gmail_api:gmail_api_token_unavailable"]


async def test_unconfigured_reader_never_raises_into_callers():
    reader = MailReadService(MailConfig(mail_app_disabled=True))
    assert not reader.any_configured
    assert await reader.fetch_recent_otp("naukri") is None
    with pytest.raises(MailReadError):
        await reader.recent(NOW)
    report = await reader.scan_recruiter_replies(MemoryStore())
    assert report.errors == ["mail_read_unconfigured"] and report.new_events == 0


# --- recruiter replies / interview watcher -------------------------------------------------------------
async def drafted_store():
    store = MemoryStore()
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="d1", url="https://x/1",
                                                      title="Backend Engineer", company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters")
    record = await store.transition(record, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")
    reservation = await store.reserve_email_draft(record.id, "naukri", "talent@acme.example.com")
    await store.complete_email_draft(reservation.draft.id, channel="imap", subject="s", body_preview="b",
                                     composer="template", enrichment_source="jd_regex", external_draft_id="x")
    return store, record


async def test_recruiter_reply_and_interview_alerts_are_deduplicated_and_pushed():
    store, record = await drafted_store()
    fake = FakeIMAP([
        rfc822("Priya <talent@acme.example.com>", "Re: Backend Engineer", "Thanks, can we talk tomorrow?",
               message_id="<r1@acme>"),
        rfc822("HR <hr@beta.example.com>", "Interview invitation", "Our recruiting team would like to schedule "
               "a technical round interview with you.", message_id="<r2@beta>"),
        rfc822("Newsletter <news@shop.example.com>", "Big sale", "Interview tips sale!", message_id="<n1@shop>"),
        rfc822("No Reply <noreply@naukri.com>", "Recruiter viewed your profile", "A recruiter viewed",
               message_id="<n2@naukri>"),
    ])
    reader = service(fake)
    sent = []

    async def notify(text):
        sent.append(text)

    report = await reader.scan_recruiter_replies(store, notify=notify)
    assert report.new_events == 2 and len(sent) == 2
    assert any(s.startswith("📬 Recruiter reply from Acme: Re: Backend Engineer") for s in sent)
    assert any(s.startswith("📬 Interview alert from beta.example.com") for s in sent)
    events = await reader.events.recent()
    linked = next(e for e in events if e.message_key == "<r1@acme>")
    assert linked.application_id == record.id and linked.platform == "naukri" and linked.alerted_at is not None
    again = await reader.scan_recruiter_replies(store, notify=notify)
    assert again.new_events == 0 and len(sent) == 2  # restart-safe dedup on Message-ID


# --- job-alert ingestion ------------------------------------------------------------------------------------
async def test_job_alert_emails_create_discovered_rows_and_linkedin_is_never_automated():
    naukri = ('<a href="https://www.naukri.com/job-listings-python-developer-acme-bengaluru-3-to-5-years-'
              '251126000123?src=alert&tok=TEST_FAKE_TOKEN_ONLY">Python Developer</a>')
    linkedin = '<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">Backend</a>'
    fake = FakeIMAP([
        rfc822("Naukri <jobalert@naukri.com>", "Job alert: 3 new Python jobs", naukri, html=True,
               message_id="<a1@naukri>"),
        rfc822("LinkedIn <jobs-noreply@linkedin.com>", "Jobs you might be interested in", linkedin, html=True,
               message_id="<a2@li>"),
        rfc822("Someone <x@example.com>", "Job alert", naukri, html=True, message_id="<a3@x>"),  # not a portal sender
    ])
    store = MemoryStore()
    report = await service(fake).scan_job_alert_emails(store)
    assert report.discovered == 2 and report.new_events == 2
    record = await store.get("naukri", "251126000123")
    assert record.state is S.DISCOVERED and record.job_url.endswith("3-to-5-years-251126000123")
    assert "TEST_FAKE_TOKEN_ONLY" not in record.job_url
    assert (await store.get("linkedin_alert", "4012345678")) is not None  # recorded only; no adapter runs it
    assert (await service(fake).scan_job_alert_emails(store)).discovered == 0  # rows already exist


async def test_mail_event_store_memory_dedup():
    events = MailEventStore()
    from backend.app.mail_v2.reader import MailEvent

    event = MailEvent("k1", "INTERVIEW", "imap", "a", "b", "c", NOW)
    assert await events.add(event) and not await events.add(MailEvent("k1", "INTERVIEW", "imap", "a", "b", "c", NOW))
    assert [e.message_key for e in await events.recent()] == ["k1"]


def test_imap_errors_map_to_fixed_codes():
    reader = ImapReadClient(IMAP_CONFIG, factory=FakeIMAP([], fail="boom"))
    with pytest.raises(MailReadError) as exc:
        reader._read(NOW, None, 5)
    assert exc.value.code == "imap_oserror"
    assert issubclass(imaplib.IMAP4.error, Exception)
