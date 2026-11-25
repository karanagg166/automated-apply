"""Phase 5 Layer 1: the READ + DRAFT ONLY mail bridge (mail_v2).

RFC 5322 construction + PDF guard, IMAP APPEND into Gmail Drafts with \\Draft,
automatic silent Mail.app fallback, argv/temp-file injection safety, the LLM
composer with its deterministic keyless fallback, and UNIQUE(application_id)
duplicate-draft prevention. No real IMAP, osascript or HTTP is ever used.
"""

import imaplib
import json
import re
from email import message_from_bytes
from pathlib import Path
from typing import ClassVar

import httpx
import pytest

from backend.app.ai_v2.router import LLMRouter
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.store import MemoryStore
from backend.app.mail_v2 import mail_app_drafts
from backend.app.mail_v2.composer import (
    DraftComposer,
    DraftJob,
    clean_llm_body,
    template_draft,
)
from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.imap_drafts import (
    ImapDraftClient,
    ImapDraftError,
    parse_drafts_mailbox,
)
from backend.app.mail_v2.mail_app_drafts import (
    MailAppDraftClient,
    MailAppDraftError,
    osascript_runner,
)
from backend.app.mail_v2.message import (
    APP_ID_HEADER,
    DraftContent,
    DraftValidationError,
    build_draft_message,
    resume_attachment,
    valid_recipient,
)
from backend.app.mail_v2.service import MailDraftService

PASSWORD = "TEST_FAKE_TOKEN_ONLY"
IMAP = MailConfig(imap_email="owner.test@example.com", imap_password=PASSWORD, mail_app_disabled=True)
PROFILE = {"full_name": "Test Candidate", "email": "owner.test@example.com", "phone": "+91 90000 00000",
           "linkedin_url": "https://www.linkedin.com/in/test-candidate", "verified_experience_years": 2,
           "verified_skills": ["Python", "FastAPI", "PostgreSQL"],
           "projects": [{"name": "Job Pulse", "technologies": ["Python"]}],
           "preferences": {"target_roles": ["Backend Engineer"], "tech_stack": ["Python", "Docker"]}}
CONTENT = DraftContent("Application: Backend Engineer at Acme", "Hi Acme hiring team,\n\nBody ✓ naïve résumé.")
MALICIOUS = 'Acme"; do shell script "rm -rf /'


class FakeIMAP:
    """imaplib.IMAP4_SSL stand-in recording every call."""
    instances: ClassVar[list["FakeIMAP"]] = []

    def __init__(self, host, port, *, login_error=None, append_error=None, append_status="OK",
                 mailbox_lines=None):
        self.host, self.port = host, port
        self.calls: list[tuple] = []
        self.login_error, self.append_error, self.append_status = login_error, append_error, append_status
        self.mailbox_lines = mailbox_lines if mailbox_lines is not None else [
            b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"']
        FakeIMAP.instances.append(self)

    def login(self, user, password):
        self.calls.append(("login", user))
        if self.login_error:
            raise self.login_error

    def list(self):
        return "OK", self.mailbox_lines

    def append(self, mailbox, flags, date_time, message):
        self.calls.append(("append", mailbox, flags, message))
        if self.append_error:
            raise self.append_error
        return self.append_status, [b"[APPENDUID 1 42]"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"3"]

    def logout(self):
        self.calls.append(("logout",))


def factory(**kw):
    def make(host, port):
        return FakeIMAP(host, port, **kw)
    return make


class FakeMailApp:
    def __init__(self, result=None, error=None):
        self.requests: list[dict] = []
        self.result = result or {"saved": True, "draft_id": "77", "attached": False}
        self.error = error

    async def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def reset_fake():
    FakeIMAP.instances.clear()


async def app_record(store, i=1):
    return await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"n-{i}",
                                                    url=f"https://example.com/{i}", title="Backend Engineer",
                                                    company="Acme"))


def mail_service(store, *, config=IMAP, imap_kw=None, mail_app=None, available=False, monkeypatch=None):
    imap = ImapDraftClient(config, factory=factory(**(imap_kw or {})))
    app = MailAppDraftClient(config, runner=mail_app or FakeMailApp())
    if monkeypatch is not None:
        monkeypatch.setattr(MailConfig, "mail_app_available", property(lambda self: available))
    return MailDraftService(store, config, imap=imap, mail_app=app)


# --- RFC 5322 message ------------------------------------------------------------------
def test_message_is_utf8_plain_text_with_idempotency_header(tmp_path):
    message = build_draft_message(CONTENT, recipient="HR@Acme.io", sender_email="owner.test@example.com",
                                  sender_name="Test Candidate", application_id="1234-abcd")
    parsed = message_from_bytes(message.as_bytes())
    assert parsed["To"] == "hr@acme.io" and parsed[APP_ID_HEADER] == "1234-abcd"
    assert parsed["From"] == "Test Candidate <owner.test@example.com>" and parsed["Message-ID"]
    assert parsed.get_content_type() == "text/plain"
    assert "naïve résumé" in parsed.get_payload(decode=True).decode("utf-8")


@pytest.mark.parametrize("recipient", ["a@b.io, c@d.io", "x@y.io\r\nBcc: z@w.io", "Name <a@b.io>", "nope", ""])
def test_recipient_must_be_exactly_one_plain_address(recipient):
    with pytest.raises(DraftValidationError):
        valid_recipient(recipient)


def test_subject_header_injection_is_neutralised():
    message = build_draft_message(DraftContent("Hi\r\nBcc: evil@x.io", "body"), recipient="a@acme.io",
                                  sender_email=None)
    assert "Bcc" not in message and message["Subject"] == "Hi Bcc: evil@x.io"


def test_resume_attachment_guard(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"0" * 100)
    assert resume_attachment(str(pdf)) == (pdf, None)
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-" + b"0" * (5 * 1024 * 1024))
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"MZ not a pdf")
    assert resume_attachment(str(big))[1] == "resume_size_invalid"
    assert resume_attachment(str(fake))[1] == "resume_not_pdf"
    assert resume_attachment(str(tmp_path / "missing.pdf"))[1] == "resume_not_found"
    message = build_draft_message(CONTENT, recipient="a@acme.io", sender_email=None, attachment=pdf)
    parts = [p.get_content_type() for p in message.iter_attachments()]
    assert parts == ["application/pdf"]


# --- IMAP ---------------------------------------------------------------------------------
def test_drafts_mailbox_detection_prefers_special_use_flag():
    assert parse_drafts_mailbox([b'(\\HasNoChildren \\Drafts) "/" "[Google Mail]/Brouillons"']) \
        == "[Google Mail]/Brouillons"
    assert parse_drafts_mailbox([b'(\\HasNoChildren) "/" "[Gmail]/Drafts"']) == "[Gmail]/Drafts"
    assert parse_drafts_mailbox([b"garbage"]) is None


async def test_imap_append_goes_to_gmail_drafts_with_the_draft_flag():
    client = ImapDraftClient(IMAP, factory=factory())
    message = build_draft_message(CONTENT, recipient="hr@acme.io", sender_email=IMAP.imap_email)
    receipt = await client.append_draft(message)
    fake = FakeIMAP.instances[0]
    (append,) = [c for c in fake.calls if c[0] == "append"]
    assert append[1] == '"[Gmail]/Drafts"' and append[2] == r"(\Draft)"
    assert b"To: hr@acme.io" in append[3] and fake.calls[-1] == ("logout",)
    assert (fake.host, fake.port) == ("imap.gmail.com", 993) and receipt.message_id == message["Message-ID"]


async def test_imap_read_only_check_uses_examine():
    result = await ImapDraftClient(IMAP, factory=factory()).check_connection()
    assert result == {"ok": True, "drafts_mailbox": "[Gmail]/Drafts", "drafts_count": 3}
    assert ("select", '"[Gmail]/Drafts"', True) in FakeIMAP.instances[0].calls


async def test_imap_errors_are_classified_definite_or_ambiguous():
    message = build_draft_message(CONTENT, recipient="hr@acme.io", sender_email=None)
    with pytest.raises(ImapDraftError) as auth:
        await ImapDraftClient(IMAP, factory=factory(login_error=imaplib.IMAP4.error("AUTHENTICATIONFAILED"))
                              ).append_draft(message)
    assert auth.value.code == "imap_auth_failed" and not auth.value.ambiguous
    with pytest.raises(ImapDraftError) as aborted:
        await ImapDraftClient(IMAP, factory=factory(append_error=imaplib.IMAP4.abort("socket closed"))
                              ).append_draft(message)
    assert aborted.value.ambiguous
    with pytest.raises(ImapDraftError) as rejected:
        await ImapDraftClient(IMAP, factory=factory(append_status="NO")).append_draft(message)
    assert rejected.value.code == "imap_append_rejected" and not rejected.value.ambiguous


# --- service: channel selection, fallback, idempotency -----------------------------------
async def test_draft_is_created_once_and_sets_draft_created_at():
    store = MemoryStore()
    record = await app_record(store)
    service = mail_service(store)
    first = await service.create_application_draft(record, "hr@acme.io", CONTENT, enrichment_source="jd_text")
    assert first.created and first.channel == "imap" and first.draft.status == "CREATED"
    again = await service.create_application_draft(await store.get_application(record.id), "hr@acme.io", CONTENT)
    stale = await service.create_application_draft(record, "other@acme.io", CONTENT)  # stale copy, no flag
    assert again.already_drafted and stale.already_drafted and not again.created
    assert sum(1 for i in FakeIMAP.instances for c in i.calls if c[0] == "append") == 1
    assert len(store.drafts) == 1 and (await store.get_application(record.id)).draft_created_at is not None


async def test_imap_auth_failure_falls_back_to_silent_mail_app(monkeypatch):
    store = MemoryStore()
    record = await app_record(store)
    runner = FakeMailApp()
    service = mail_service(store, imap_kw={"login_error": imaplib.IMAP4.error("AUTHENTICATIONFAILED")},
                           mail_app=runner, available=True, monkeypatch=monkeypatch)
    outcome = await service.create_application_draft(record, "hr@acme.io", CONTENT)
    assert (outcome.created, outcome.channel, outcome.fell_back) == (True, "mail_app", True)
    assert runner.requests == [{"action": "draft", "recipient": "hr@acme.io", "subject": CONTENT.subject,
                                "body": CONTENT.body}]
    assert store.drafts[0]["channel"] == "mail_app"


async def test_ambiguous_imap_outcome_never_falls_back_or_retries(monkeypatch):
    store = MemoryStore()
    record = await app_record(store)
    runner = FakeMailApp()
    service = mail_service(store, imap_kw={"append_error": OSError("connection reset")}, mail_app=runner,
                           available=True, monkeypatch=monkeypatch)
    outcome = await service.create_application_draft(record, "hr@acme.io", CONTENT)
    assert outcome.ambiguous and not outcome.created and runner.requests == []
    assert store.drafts[0]["status"] == "PENDING"  # parked: may exist in Gmail already
    retry = await service.create_application_draft(record, "hr@acme.io", CONTENT)
    assert retry.already_drafted and runner.requests == []


async def test_definite_failure_can_be_retried_later():
    store = MemoryStore()
    record = await app_record(store)
    failing = mail_service(store, imap_kw={"append_status": "NO"})
    assert (await failing.create_application_draft(record, "hr@acme.io", CONTENT)).error == "imap_append_rejected"
    assert store.drafts[0]["status"] == "FAILED"
    ok = await mail_service(store).create_application_draft(record, "hr@acme.io", CONTENT)
    assert ok.created and len(store.drafts) == 1 and store.drafts[0]["status"] == "CREATED"


async def test_unconfigured_mail_creates_nothing():
    store = MemoryStore()
    record = await app_record(store)
    service = MailDraftService(store, MailConfig(mail_app_disabled=True))
    outcome = await service.create_application_draft(record, "hr@acme.io", CONTENT)
    assert outcome.error == "mail_unconfigured" and store.drafts == []
    assert service.status()["active_channel"] == "unconfigured"


async def test_test_draft_is_marked_and_not_persisted():
    store = MemoryStore()
    outcome = await mail_service(store).save_test_draft("hr@acme.io", CONTENT)
    (append,) = [c for c in FakeIMAP.instances[0].calls if c[0] == "append"]
    assert outcome.created and b"Subject: [TEST DRAFT] Application" in append[3] and store.drafts == []


# --- Mail.app: argv / temp-file injection safety, never send or activate ------------------
async def test_osascript_gets_only_a_temp_file_path_never_the_untrusted_text(monkeypatch):
    seen = {}

    class Child:
        returncode = 0

        async def communicate(self):
            return json.dumps({"saved": True, "draft_id": "9"}).encode(), b""

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        seen["request"] = json.loads(Path(args[-1]).read_text())
        seen["mode"] = Path(args[-1]).stat().st_mode & 0o777
        return Child()

    monkeypatch.setattr(mail_app_drafts.asyncio, "create_subprocess_exec", fake_exec)
    subject = f"Application at {MALICIOUS}"
    result = await osascript_runner({"action": "draft", "recipient": "hr@acme.io", "subject": subject,
                                     "body": MALICIOUS})
    args = seen["args"]
    assert args[:4] == ("/usr/bin/osascript", "-l", "JavaScript", str(mail_app_drafts.SCRIPT))
    assert len(args) == 5 and MALICIOUS not in " ".join(args) and "-e" not in args
    assert seen["request"]["subject"] == subject and seen["mode"] == 0o600  # passed verbatim as data
    assert not Path(args[-1]).exists() and result["saved"] is True  # temp file removed


def test_mail_app_script_has_no_send_or_activate_and_saves_invisibly():
    script = mail_app_drafts.SCRIPT.read_text()
    lowered = script.lower()
    assert "activate" not in lowered and not re.search(r"\bsend\b|\.send\(|sendmessage", lowered)
    assert "visible: false" in script and "mail.save(draft)" in script and "JSON.parse" in script


async def test_mail_app_permission_denied_and_unconfirmed_results(monkeypatch):
    monkeypatch.setattr(MailConfig, "mail_app_available", property(lambda self: True))
    denied = MailAppDraftClient(MailConfig(), runner=FakeMailApp({"error": "x", "apple_event_code": -1743}))
    with pytest.raises(MailAppDraftError, match="automation_permission_required"):
        await denied.save_draft(recipient="a@acme.io", subject="s", body="b")
    unsure = MailAppDraftClient(MailConfig(), runner=FakeMailApp({"saved": False}))
    with pytest.raises(MailAppDraftError) as error:
        await unsure.save_draft(recipient="a@acme.io", subject="s", body="b")
    assert error.value.ambiguous


# --- composer --------------------------------------------------------------------------------
JOB = DraftJob(role_title="Backend Engineer", company_name="Acme", platform="naukri",
               jd_text="We build Python and FastAPI services on PostgreSQL.", recipient_first_name="Asha")


async def test_keyless_composer_uses_a_truthful_deterministic_template():
    content = await DraftComposer(None).compose(JOB, PROFILE, has_attachment=True)
    assert content.composer == "template" and content.subject == "Application: Backend Engineer at Acme"
    assert content.body.startswith("Hi Asha,\n\n") and "on Naukri" in content.body
    assert "2 years" in content.body and "Python, FastAPI, PostgreSQL" in content.body and "Job Pulse" in content.body
    assert "My resume is attached." in content.body
    assert content.body.rstrip().endswith("https://www.linkedin.com/in/test-candidate")
    assert "Docker" not in content.body  # tech_stack entries absent from the JD are not claimed as matches


def test_template_without_years_or_jd_still_reads_well():
    content = template_draft(DraftJob("Engineer", None), {"verified_skills": ["Go"]}, has_attachment=False)
    assert "My day-to-day work is centred on Go." in content.body and "your team" in content.body


def llm_router(reply=None, status=200):
    bodies: list[str] = []

    def handler(request):
        bodies.append(request.content.decode())
        if status != 200:
            return httpx.Response(status, json={})
        text = json.dumps(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 50, "completion_tokens": 50}})

    router = LLMRouter(env={"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY", "GEMINI_API_KEY": ""},
                       usage=MemoryUsageStore(), transport=httpx.MockTransport(handler))
    router.register_secrets(["Test Candidate", "+91 90000 00000", "owner.test@example.com"])
    return router, bodies


GOOD_BODY = ("I am a backend engineer who builds Python and FastAPI services backed by PostgreSQL. " * 3
             + "Recently I shipped Job Pulse, an automation service, end to end. " * 2
             + "I would welcome a short conversation about how I could help your platform team ship faster.")


async def test_llm_composer_gets_only_the_scrubbed_profile_and_signs_off_locally():
    router, bodies = llm_router({"subject": "Backend Engineer role at Acme", "body": "Hi there,\n\n" + GOOD_BODY
                                 + "\n\nBest regards,\nSomeone"})
    content = await DraftComposer(router).compose(JOB, PROFILE)
    assert content.composer == "llm" and content.provider == "groq"
    assert content.body.startswith("Hi Asha,\n\nI am a backend engineer") and "Someone" not in content.body
    assert content.body.count("Best regards,") == 1 and "Test Candidate" in content.body
    prompt = bodies[0]
    for secret in ("Test Candidate", "90000", "owner.test@example.com", "linkedin.com/in/test-candidate"):
        assert secret not in prompt


@pytest.mark.parametrize("reply", [
    {"subject": "Backend role", "body": GOOD_BODY + " Regards, [Your Name]"},
    {"subject": "Rockstar ninja wanted", "body": GOOD_BODY},
    {"subject": "Backend role", "body": "Too short to be a real email body but long enough for the schema " * 2},
])
async def test_rejected_llm_output_falls_back_to_the_template(reply):
    router, _ = llm_router(reply)
    assert (await DraftComposer(router).compose(JOB, PROFILE)).composer == "template"


async def test_exhausted_llm_chain_falls_back_to_the_template():
    router, bodies = llm_router(status=503)
    content = await DraftComposer(router).compose(JOB, PROFILE)
    assert content.composer == "template" and len(bodies) == 1


def test_clean_llm_body_strips_greeting_and_closing():
    assert clean_llm_body("Dear Sir,\n\n" + GOOD_BODY + "\n\nThanks,\nBob") == GOOD_BODY.strip()


def test_mail_config_from_env_hides_the_password():
    config = MailConfig.from_env({"GMAIL_IMAP_EMAIL": "karan.test@example.com",
                                  "GMAIL_IMAP_APP_PASSWORD": "abcd efgh ijkl mnop", "MAIL_DRAFT_CHANNEL": "bogus"})
    assert config.imap_password == "abcdefghijklmnop" and config.channel == "auto"
    assert "abcd" not in repr(config) and "abcd" not in json.dumps(config.public())
    assert config.public()["imap_email"] == "ka•••@example.com" and config.active_channel() == "imap"
    assert MailConfig.from_env({"MAIL_V2_DISABLED": "true"}).active_channel() == "unconfigured"
