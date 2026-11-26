"""Phase 9B job-alert e-mail links: Greenhouse / Lever / Ashby / Instahyre / Internshala -> P1 rows (no network)."""

from __future__ import annotations

from backend.app.browser_v2.store import MemoryStore
from backend.app.mail_v2.read_models import JOB_LINKS
from backend.app.mail_v2.read_parsing import alert_job_links
from backend.tests.test_mail_v2_reader import FakeIMAP, rfc822, service

GH = "https://job-boards.greenhouse.io/acme/jobs/4012345?gh_src=alert&amp;t=TEST_FAKE_TOKEN_ONLY"
LEVER = "https://jobs.lever.co/beta/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab/apply?lever-source=mail"
ASHBY = "https://jobs.ashbyhq.com/gamma/11111111-2222-3333-4444-555555555555?utm_source=alert"
INSTAHYRE = "https://www.instahyre.com/job-123456-backend-developer-at-delta/?ref=mail"
INTERNSHALA = "https://internshala.com/job/detail/python-developer-job-at-eps1234567?utm=mail"


def test_alert_links_are_recognised_per_source_and_stripped_of_tracking():
    body = f"{GH} {LEVER} {ASHBY} {INSTAHYRE} {INTERNSHALA}"
    any_sender = alert_job_links(None, body, JOB_LINKS)
    assert set(any_sender) == {("greenhouse", "4012345"), ("lever", "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"),
                               ("ashby", "11111111-2222-3333-4444-555555555555")}
    assert any_sender[("greenhouse", "4012345")] == "https://job-boards.greenhouse.io/acme/jobs/4012345"
    assert "?" not in "".join(any_sender.values())
    assert ("instahyre", "123456") in alert_job_links("instahyre", body, JOB_LINKS)
    assert ("internshala", "1234567") in alert_job_links("internshala", body, JOB_LINKS)


async def test_alert_mails_queue_ats_and_portal_links_as_p1_and_linkedin_stays_notify_only():
    linkedin = '<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">Backend</a>'
    fake = FakeIMAP([
        rfc822("Jobs Digest <digest@newsletter.example>", "New jobs for you", f'<a href="{GH}">GH</a> '
               f'<a href="{LEVER}">Lever</a> <a href="{INSTAHYRE}">not from instahyre</a>', html=True,
               message_id="<b1@x>"),
        rfc822("Instahyre <jobs@instahyre.com>", "Recommended jobs", f'<a href="{INSTAHYRE}">x</a>', html=True,
               message_id="<b2@x>"),
        rfc822("Internshala <alerts@internshala.com>", "Job alert: Python", INTERNSHALA, message_id="<b3@x>"),
        rfc822("LinkedIn <jobs-noreply@linkedin.com>", "Jobs you might be interested in", linkedin, html=True,
               message_id="<b4@x>"),
        rfc822("Lever <x@lever.co>", "Thanks for applying", LEVER, message_id="<b5@x>"),  # not an alert subject
    ])
    store = MemoryStore()
    report = await service(fake).scan_job_alert_emails(store)
    assert report.new_events == 4 and report.discovered == 5
    for platform, job_id in (("greenhouse", "4012345"), ("lever", "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"),
                             ("instahyre", "123456"), ("internshala", "1234567")):
        record = await store.get(platform, job_id)
        assert record is not None and record.priority == 1 and record.priority_reason == "job_alert_email"
        assert record.discovered_via == f"mail_alert:{platform}"
    linked = await store.get("linkedin_alert", "4012345678")
    assert linked is not None and linked.priority == 2 and linked.discovered_via is None  # never queued urgently
    greenhouse = await store.get("greenhouse", "4012345")
    assert greenhouse is not None and "TEST_FAKE_TOKEN_ONLY" not in (greenhouse.job_url or "")
    assert (await service(fake).scan_job_alert_emails(store)).discovered == 0
