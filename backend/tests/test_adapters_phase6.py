"""Phase 6A portal adapters on a real headless Chromium with fully intercepted, synthetic pages.

Covers discovery, form extraction/filling, HITL hand-off, dry-run stop points, submission
receipts, ambiguous outcomes, limit/challenge detection and external-ATS delegation for the
9 new adapters, plus live Naukri OTP entry. No request leaves the machine.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from backend.app.browser_v2.adapters.base import JobDetail, JobListing, PortalAdapter
from backend.app.browser_v2.adapters.common import (
    HostedAtsApplier,
    HostedFormFiller,
    classify_ats,
    deterministic_intro,
    html_to_text,
)
from backend.app.browser_v2.adapters.greenhouse import (
    GreenhouseAdapter,
    board_from_url,
    board_map,
)
from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter, parse_jobs
from backend.app.browser_v2.adapters.hiringcafe import HiringCafeAdapter
from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
from backend.app.browser_v2.adapters.internshala import InternshalaAdapter
from backend.app.browser_v2.adapters.lever import LeverAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.adapters.we_work_remotely import (
    WeWorkRemotelyAdapter,
    parse_rss,
)
from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
from backend.app.browser_v2.adapters.work_at_a_startup import WorkAtAStartupAdapter
from backend.app.browser_v2.portals import ADAPTER_READY, PORTALS, adapter_status
from backend.app.browser_v2.rules import UNKNOWN_APPLICANTS
from backend.app.browser_v2.service import default_adapters, job_id_from_url
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.state import ReplayRefused
from backend.tests.phase6a_fixtures import (  # noqa: F401
    NOW,
    chromium_fixture,
    days_ago,
    facts,
    html,
    web_fixture,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),  # one browser per module
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

GH_JOB = "https://boards.greenhouse.io/acme/jobs/4012345"
LEVER_ID = "5f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
LEVER_JOB = f"https://jobs.lever.co/acme/{LEVER_ID}"
ZETA_ID = "9a8b7c6d-1111-2222-3333-444455556666"


def gh_form(*, submit_js: str | None = None, extra: str = "") -> str:
    onsubmit = f'onsubmit="{submit_js}"' if submit_js else ""
    return html(f"""
      <h1>Backend Engineer</h1>
      <form id="application_form" action="/acme/jobs/4012345/confirmation" method="get" {onsubmit}>
        <label for="first_name">First Name *</label><input id="first_name" name="first_name" required>
        <label for="last_name">Last Name *</label><input id="last_name" name="last_name" required>
        <label for="email">Email *</label><input id="email" name="email" type="email" required>
        <label for="phone">Phone</label><input id="phone" name="phone" type="tel">
        <label for="resume">Resume/CV *</label><input id="resume" name="resume" type="file" required>
        <label for="li">LinkedIn Profile</label><input id="li" name="li">
        <label for="q1">Are you legally authorized to work in India? *</label>
        <select id="q1" name="q1" required><option value="">Select...</option><option>Yes</option><option>No</option></select>
        <label for="q2">How many years of experience do you have with Python? *</label><input id="q2" name="q2" required>
        <label for="gender">Gender</label><select id="gender" name="gender"><option value="">Select</option><option>Decline to self identify</option></select>
        {extra}
        <button type="submit" id="submit_app">Submit Application</button>
      </form>""")


def gh_detail(**overrides) -> JobDetail:
    listing = JobListing(platform="greenhouse", external_job_id="4012345", url=GH_JOB, title="Backend Engineer",
                         company="Acme")
    values = dict(listing=listing, applicants=UNKNOWN_APPLICANTS, posted_age_days=2, already_applied=False,
                  apply_mode="direct", description="Python FastAPI PostgreSQL backend", apply_url=GH_JOB,
                  ats="greenhouse")
    values.update(overrides)
    return JobDetail(**values)


AUTH_ANSWER = {"Are you legally authorized to work in India?": "Yes"}


# --- registry ---------------------------------------------------------------------------------------------
def test_all_ten_portals_have_ready_adapters_satisfying_the_protocol():
    adapters = default_adapters()
    assert set(adapters) == set(PORTALS) == set(ADAPTER_READY)
    assert all(adapter_status(name) == "ready" for name in PORTALS)
    for adapter in adapters.values():
        assert isinstance(adapter, PortalAdapter), adapter.platform


@pytest.mark.parametrize("platform,url,expected", [
    ("greenhouse", GH_JOB, "4012345"),
    ("lever", LEVER_JOB, LEVER_ID),
    ("we_work_remotely", "https://weworkremotely.com/remote-jobs/acme-backend-engineer", "acme-backend-engineer"),
    ("instahyre", "https://www.instahyre.com/job-283941-python-developer-at-acme-bangalore/", "283941"),
    ("internshala", "https://internshala.com/job/detail/python-developer-job-at-acme1234567", "1234567"),
    ("wellfound", "https://wellfound.com/jobs/3456789-backend-engineer", "3456789"),
    ("work_at_a_startup", "https://www.workatastartup.com/jobs/65432", "65432"),
    ("hiringcafe", "https://hiring.cafe/viewjob/abc123xyz", "abc123xyz"),
    ("naukri", "https://www.naukri.com/job-listings-python-developer-acme-bengaluru-3-to-5-years-251126000123",
     "251126000123"),
    ("greenhouse", "http://boards.greenhouse.io/acme/jobs/1", None),
])
def test_job_id_from_url(platform, url, expected):
    assert job_id_from_url(platform, url) == expected


def test_ats_classification_and_helpers():
    assert classify_ats(GH_JOB) == "greenhouse"
    assert classify_ats("https://job-boards.greenhouse.io/acme/jobs/77") == "greenhouse"
    assert classify_ats(LEVER_JOB) == "lever" and classify_ats(LEVER_JOB + "/apply") == "lever"
    assert classify_ats("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1") is None
    assert classify_ats("http://boards.greenhouse.io/acme/jobs/1") is None  # https only
    assert html_to_text("&lt;p&gt;Python &amp;amp; Go&lt;/p&gt;<script>x()</script>") == "Python & Go"
    assert board_map({"acme": "Acme", "bad token!": "x"}) == {"acme": "Acme"}
    assert board_map(["acme", "beta"]) == {"acme": None, "beta": None}
    assert board_from_url(GH_JOB) == "acme"


# --- Greenhouse: discovery via the reused public-API source ---------------------------------------------
def greenhouse_api(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "boards-api.greenhouse.io" and request.url.path == "/v1/boards/acme/jobs"
    return httpx.Response(200, json={"jobs": [
        {"id": 4012345, "title": "Senior Backend Engineer", "absolute_url": GH_JOB,
         "location": {"name": "Remote - India"}, "content": "&lt;p&gt;Python, FastAPI&lt;/p&gt;",
         "first_published": days_ago(2), "updated_at": days_ago(1)},
        {"id": 4012346, "title": "Account Executive", "absolute_url": "https://boards.greenhouse.io/acme/jobs/4012346",
         "location": {"name": "Pune"}, "content": "Sales", "first_published": days_ago(1)},
        {"id": 4012347, "title": "Backend Engineer II", "absolute_url": "https://boards.greenhouse.io/acme/jobs/4012347",
         "location": {"name": "Remote"}, "content": "Go", "first_published": days_ago(40)},
    ]})


async def test_greenhouse_discovers_role_matched_recent_jobs_from_configured_boards():
    async with httpx.AsyncClient(transport=httpx.MockTransport(greenhouse_api)) as client:
        adapter = GreenhouseAdapter(http_client=client)
        adapter.configure({"preferences": {"greenhouse_boards": {"acme": "Acme"}}})
        jobs = await adapter.discover_jobs(None, query="Backend Engineer", limit=10, job_age_days=7)
    assert [(j.external_job_id, j.company, j.posted_age_days) for j in jobs] == [("4012345", "Acme", 2)]
    assert adapter.jobs["4012345"].description == "Python, FastAPI" and adapter.jobs["4012345"].apply_url == GH_JOB


async def test_greenhouse_full_flow_hitl_then_confirmed_receipt(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_form())
    site.add(GH_JOB + "/confirmation", html("<h2>Thank you for applying to Acme!</h2>"))
    adapter = GreenhouseAdapter(receipts_root=tmp_path / "receipts", settle_ms=10, confirm_timeout_s=5)
    candidate = facts(tmp_path)
    first = await adapter.apply_job(page, gh_detail(), candidate, dry_run=False)
    assert first.state is S.WAITING_FOR_USER and first.question is not None
    assert first.question.prompt == "Are you legally authorized to work in India?"
    assert first.question.options == ("Yes", "No") and not first.clicked_apply
    await page.goto("about:blank")  # the next cycle re-opens the form fresh (inspect_job navigates)
    result = await adapter.apply_job(page, gh_detail(), candidate, dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.APPLIED and result.clicked_apply and result.reason == "confirmed"
    assert result.receipt["source"].startswith("confirmation_text") and result.receipt["ats"] == "greenhouse"
    assert result.receipt["resume"] == "backend"  # JD mentions FastAPI/PostgreSQL -> backend variant
    filled = {a["question"]: (a["answer"], a["source"]) for a in result.answers}
    assert filled["First Name"] == ("first_name", "profile_identity")  # identity typed, value never logged
    assert filled["How many years of experience do you have with Python?"] == ("3", "profile")
    assert filled["Are you legally authorized to work in India?"] == ("Yes", "human_hitl")
    assert "Gender" not in filled  # optional EEO questions are never guessed
    submitted = site.hits[-1]
    assert "first_name=Test" in submitted and "q1=Yes" in submitted and "q2=3" in submitted
    assert (tmp_path / "receipts" / "greenhouse").is_dir() and result.screenshot


async def test_greenhouse_dry_run_fills_but_never_uploads_or_submits(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_form())
    adapter = GreenhouseAdapter(receipts_root=tmp_path / "r", settle_ms=10)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=True, hitl_answers=AUTH_ANSWER)
    assert result.state is S.SCORED and result.reason == "dry_run_stopped_before_submit" and not result.clicked_apply
    assert "upload backend.pdf" in result.planned_action
    assert not any("confirmation" in hit for hit in site.hits)
    assert await page.evaluate("document.getElementById('resume').files.length") == 0
    assert (tmp_path / "r" / "failures").is_dir()  # dry-run screenshot goes to the ring buffer


async def test_greenhouse_validation_errors_become_an_error_hitl(web, tmp_path):
    page, site = web
    js = ("event.preventDefault();document.getElementById('err').style.display='block';"
          "document.getElementById('email').setAttribute('aria-invalid','true');")
    site.add(GH_JOB, gh_form(submit_js=js, extra='<div id="err" class="field-error" style="display:none">'
                                                  'Email is invalid</div>'))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=3)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.WAITING_FOR_USER and result.reason == "ats_validation_errors" and result.clicked_apply
    assert result.question.kind == "ERROR" and "Email is invalid" in result.question.prompt


async def test_greenhouse_ambiguous_submit_is_submission_unknown(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_form())
    site.add(GH_JOB + "/confirmation", html("<p>Loading…</p>"))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=1)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    # The URL alone (/confirmation) is a concrete signal; a blank page on an unrelated URL is not:
    assert result.state is S.APPLIED and result.receipt["source"] == "confirmation_url"
    site.add(GH_JOB, gh_form().replace("/acme/jobs/4012345/confirmation", "/acme/jobs/4012345/next"))
    site.add(GH_JOB + "/next", html("<p>Loading…</p>"))
    again = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert again.state is S.SUBMISSION_UNKNOWN and again.reason == "confirmation_ambiguous" and again.clicked_apply


async def test_greenhouse_closed_posting_and_captcha_are_detected_before_any_click(web, tmp_path):
    page, site = web
    site.add(GH_JOB, html("<h1>Sorry</h1><p>This job is no longer accepting applications.</p>"))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10)
    closed = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False)
    assert closed.state is S.FILTERED_OUT and closed.reason == "ats_posting_closed"
    await page.goto("about:blank")
    site.add(GH_JOB, gh_form(extra='<iframe src="https://hcaptcha.com/checkbox" style="width:300px;height:80px">'
                                   "</iframe>"))
    captcha = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False)
    assert captcha.state is S.WAITING_FOR_USER and captcha.question.kind == "CAPTCHA" and not captcha.clicked_apply


async def test_missing_resume_for_required_upload_asks_the_owner(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_form())
    candidate = facts(tmp_path, resume_files={})
    result = await GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10).apply_job(
        page, gh_detail(), candidate, dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.WAITING_FOR_USER and "no resume" in result.question.prompt.lower()
    assert result.question.input_kind == "file"


async def test_never_replay_is_enforced_by_every_new_adapter(tmp_path):
    for adapter in default_adapters().values():
        for state in ("APPLIED", "SUBMISSION_UNKNOWN", "APPLYING", "WAITING_FOR_USER"):
            with pytest.raises(ReplayRefused):
                await adapter.apply_job(object(), gh_detail(), facts(tmp_path), dry_run=True, existing_state=state)


# --- Lever ------------------------------------------------------------------------------------------------
def lever_api(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "api.lever.co" and request.url.path in ("/v0/postings/acme", "/v0/postings/zeta")
    board = request.url.path.rsplit("/", 1)[-1]
    if board == "zeta":
        url = f"https://jobs.lever.co/zeta/{ZETA_ID}"
        return httpx.Response(200, json=[{"id": ZETA_ID, "text": "Backend Engineer", "hostedUrl": url,
                                          "applyUrl": url + "/apply", "createdAt": int(NOW.timestamp() * 1000),
                                          "categories": {"location": "Remote"}, "descriptionPlain": "Python"}])
    created = int((NOW.timestamp() - 86400) * 1000)
    return httpx.Response(200, json=[{"id": LEVER_ID, "text": "Backend Engineer", "hostedUrl": LEVER_JOB,
                                      "applyUrl": LEVER_JOB + "/apply", "createdAt": created,
                                      "categories": {"location": "Bengaluru", "commitment": "Full-time"},
                                      "descriptionPlain": "Python services", "workplaceType": "remote"}])


LEVER_FORM = html("""
  <form action="/acme/%s/thanks" method="get">
    <label>Full name<span>✱</span><input name="name" required></label>
    <label>Email<input name="email" type="email" required></label>
    <label>Phone<input name="phone"></label>
    <label>Resume/CV<input name="resume" type="file"></label>
    <label>Current company<input name="org"></label>
    <label>LinkedIn URL<input name="urls[LinkedIn]"></label>
    <button type="submit">Submit application</button>
  </form>""" % LEVER_ID)


async def test_lever_discovery_and_hosted_form_apply(web, tmp_path):
    page, site = web
    async with httpx.AsyncClient(transport=httpx.MockTransport(lever_api)) as client:
        adapter = LeverAdapter(http_client=client, receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
        adapter.configure({"preferences": {"lever_boards": ["acme"]}})
        jobs = await adapter.discover_jobs(None, query="backend engineer", limit=5, job_age_days=7)
        assert [j.external_job_id for j in jobs] == [LEVER_ID] and jobs[0].posted_age_days == 1
        site.add(LEVER_JOB + "/apply", LEVER_FORM)
        site.add(LEVER_JOB + "/thanks", html("<h2>Application submitted!</h2>"))
        detail = await adapter.inspect_job(page, jobs[0])
        assert detail.apply_mode == "direct" and detail.ats == "lever" and detail.work_mode == "remote"
        assert page.url.endswith("/apply")  # inspection opened the hosted form (CAPTCHA/closed checks)
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.receipt["ats"] == "lever"
    submitted = site.hits[-1]
    assert "name=Test+Candidate" in submitted and "org=" in submitted.split("&org=")[0] + "&org="
    assert "urls%5BLinkedIn%5D=https" in submitted


# --- Himalayas / We Work Remotely / HiringCafe: external ATS handoff ----------------------------------------
HIMALAYAS_PAYLOAD = {"jobs": [
    {"title": "Backend Engineer", "companyName": "Acme", "guid": "https://himalayas.app/companies/acme/jobs/backend-engineer",
     "applicationLink": GH_JOB, "pubDate": int(NOW.timestamp()) - 86400, "description": "<p>Python</p>",
     "locationRestrictions": ["India"], "minSalary": 30000, "maxSalary": 50000, "currency": "USD"},
    {"title": "Backend Developer", "companyName": "Beta", "guid": "https://himalayas.app/companies/beta/jobs/backend-dev",
     "applicationLink": "https://beta.wd1.myworkdayjobs.com/careers/job/1", "pubDate": int(NOW.timestamp()) - 3600},
]}


def test_himalayas_parse():
    jobs = parse_jobs(HIMALAYAS_PAYLOAD)
    assert [j.external_job_id for j in jobs] == ["acme:backend-engineer", "beta:backend-dev"]
    assert jobs[0].salary_text == "USD 30,000 - 50,000 per year" and jobs[0].description == "Python"


async def test_himalayas_delegates_greenhouse_and_classifies_unknown_ats(web, tmp_path):
    page, site = web
    calls = []

    def api(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=HIMALAYAS_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client:
        adapter = HimalayasAdapter(http_client=client, receipts_root=tmp_path, settle_ms=10)
        jobs = await adapter.discover_jobs(None, query="backend engineer", limit=10, job_age_days=7)
        await adapter.discover_jobs(None, query="backend engineer", limit=10, job_age_days=7)
    assert len(calls) == 1 and "q=backend+engineer" in calls[0]  # 30-minute polite cache
    site.add(GH_JOB, gh_form())
    acme = await adapter.inspect_job(page, jobs[0])
    assert acme.apply_mode == "direct" and acme.ats == "greenhouse"
    dry = await adapter.apply_job(page, acme, facts(tmp_path), dry_run=True, hitl_answers=AUTH_ANSWER)
    assert dry.state is S.SCORED and dry.reason == "dry_run_stopped_before_submit"
    beta = await adapter.inspect_job(page, jobs[1])
    other = await adapter.apply_job(page, beta, facts(tmp_path), dry_run=False)
    assert beta.apply_mode == "external" and other.state is S.FILTERED_OUT
    assert other.reason == "external_unsupported_ats:beta.wd1.myworkdayjobs.com" and not other.clicked_apply


WWR_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Acme: Senior Backend Engineer</title><region>Anywhere in the World</region>
<link>https://weworkremotely.com/remote-jobs/acme-senior-backend-engineer</link>
<pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate><description>&lt;p&gt;Python&lt;/p&gt;</description></item>
<item><title>Spam</title><link>https://evil.example.com/remote-jobs/x</link></item>
</channel></rss>""".encode()


async def test_we_work_remotely_rss_then_lever_handoff_with_attribution(web, tmp_path):
    page, site = web
    assert [j.external_job_id for j in parse_rss(WWR_RSS)] == ["acme-senior-backend-engineer"]
    assert parse_rss(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>') == []

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=WWR_RSS))) as c:
        adapter = WeWorkRemotelyAdapter(http_client=c, receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
        jobs = await adapter.discover_jobs(None, query="backend engineer", limit=5, job_age_days=7)
    assert [(j.title, j.company) for j in jobs] == [("Senior Backend Engineer", "Acme")]
    site.add("https://weworkremotely.com/remote-jobs/acme-senior-backend-engineer",
             html(f'<h1>Senior Backend Engineer</h1><a id="job-cta-alt" href="{LEVER_JOB}">Apply for this position</a>'))
    site.add(LEVER_JOB + "/apply", LEVER_FORM)
    site.add(LEVER_JOB + "/thanks", html("<h2>Application submitted!</h2>"))
    detail = await adapter.inspect_job(page, jobs[0])
    assert detail.ats == "lever" and detail.apply_url == LEVER_JOB
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and "We Work Remotely" in result.receipt["attribution"]


async def test_hiringcafe_cards_and_greenhouse_delegation(web, tmp_path):
    page, site = web
    adapter = HiringCafeAdapter(receipts_root=tmp_path, settle_ms=10, jitter=(0, 0))
    url = adapter.search_url("backend engineer", 7)
    assert url.startswith("https://hiring.cafe/?searchState=") and "dateFetchedPastNDays" in url
    site.add("https://hiring.cafe", html(
        '<article class="job-card"><a href="/viewjob/abc123xyz"><h3>Backend Engineer</h3></a>'
        '<span class="company">Acme</span><span>Posted 2 days ago</span></article>'))
    assert (await adapter.check_session(page)).status.value == "OK"
    jobs = await adapter.discover_jobs(page, query="backend engineer", limit=5, job_age_days=7)
    assert [(j.external_job_id, j.posted_age_days) for j in jobs] == [("abc123xyz", 2)]
    site.add("https://hiring.cafe/viewjob/abc123xyz", html(
        f'<h1>Backend Engineer</h1><div class="company">Acme</div><div class="description">Python</div>'
        f'<a href="{GH_JOB}">Apply now</a>'))
    detail = await adapter.inspect_job(page, jobs[0])
    assert detail.apply_mode == "external" and detail.ats == "greenhouse"
    site.add(GH_JOB, gh_form())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True, hitl_answers=AUTH_ANSWER)
    assert result.state is S.SCORED and result.reason == "dry_run_stopped_before_submit"


# --- interactive Brave portals --------------------------------------------------------------------------------
INSTAHYRE_JOB = "https://www.instahyre.com/job-283941-python-developer-at-acme-bangalore"
MODAL_JS = """
document.getElementById('apply').onclick = () => {
  document.getElementById('modal').style.display = 'block';
};
document.getElementById('send').onclick = (e) => {
  e.preventDefault();
  if (!document.getElementById('relocate').value) { return; }
  document.getElementById('modal').style.display = 'none';
  document.getElementById('apply').innerText = 'Applied';
  document.getElementById('toast').innerText = 'Application sent successfully';
};
"""


def instahyre_job(extra: str = "", applied: bool = False) -> str:
    button = "Applied" if applied else "Apply"
    return html(f"""
      <nav><a href="/candidate/profile/">My profile</a></nav>
      <h1>Python Developer</h1><div class="company-name">Acme</div>
      <div class="job-description">Python FastAPI microservices. Posted 2 days ago. 45 applicants</div>
      <button id="apply">{button}</button>
      <div id="modal" role="dialog" style="display:none">
        <label for="relocate">Are you willing to relocate to Bengaluru? *</label>
        <select id="relocate" required><option value="">Select</option><option>Yes</option><option>No</option></select>
        <button id="send">Submit</button>
      </div>
      <div id="toast"></div>{extra}
      <script>{MODAL_JS}</script>""")


async def test_instahyre_session_discovery_and_modal_apply(web, tmp_path):
    page, site = web
    adapter = InstahyreAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0),
                               confirm_timeout_s=3)
    site.add("https://www.instahyre.com/candidate/opportunities",
             html('<a href="/candidate/profile/">Profile</a>'
                  '<div class="job-card"><a href="/job-283941-python-developer-at-acme-bangalore/">Python Developer</a>'
                  '<span class="company-name">Acme</span><span>Posted 2 days ago</span><span>45 applicants</span></div>'))
    assert (await adapter.check_session(page)).status.value == "OK"
    jobs = await adapter.discover_jobs(page, query="python developer", limit=10)
    assert len(jobs) == 1 and jobs[0].external_job_id == "283941" and jobs[0].company == "Acme"
    assert jobs[0].posted_age_days == 2 and jobs[0].applicants.minimum == 45
    site.add(INSTAHYRE_JOB, instahyre_job())
    detail = await adapter.inspect_job(page, jobs[0])
    assert detail.apply_mode == "direct" and detail.title if hasattr(detail, "title") else True
    assert detail.listing.title == "Python Developer" and "FastAPI" in (detail.description or "")
    dry = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    assert dry.state is S.SCORED and dry.reason == "dry_run_stopped_before_apply_click"
    assert await page.evaluate("getComputedStyle(document.getElementById('modal')).display") == "none"
    live = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert live.state is S.APPLIED and live.clicked_apply, live
    assert live.answers[0]["question"] == "Are you willing to relocate to Bengaluru?"
    assert live.answers[0]["answer"] == "Yes" and live.answers[0]["source"] == "profile"


async def test_instahyre_limit_already_applied_and_login(web, tmp_path):
    page, site = web
    adapter = InstahyreAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0))
    listing = JobListing(platform="instahyre", external_job_id="283941", url=INSTAHYRE_JOB)
    site.add(INSTAHYRE_JOB, instahyre_job("<p>You have reached your daily application limit.</p>"))
    limited = await adapter.inspect_job(page, listing)
    result = await adapter.apply_job(page, limited, facts(tmp_path), dry_run=False)
    assert limited.portal_limit and result.state is S.QUOTA_HIT_PENDING
    site.add(INSTAHYRE_JOB, instahyre_job(applied=True))
    applied = await adapter.inspect_job(page, listing)
    assert applied.already_applied
    result = await adapter.apply_job(page, applied, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.reason == "already_applied_on_portal"
    site.add("https://www.instahyre.com/candidate/opportunities", html('<form action="/login/"><input type="password"></form>'))
    session = await adapter.check_session(page)
    assert session.status.value == "AUTH_REQUIRED" and session.refreshed and session.reason == "login"


INTERNSHALA_JOB = "https://internshala.com/job/detail/python-developer-job-at-acme1234567"
INTERNSHALA_FORM = "https://internshala.com/application/form/1234567"


async def test_internshala_form_page_with_cover_letter_and_hitl_availability(web, tmp_path):
    page, site = web

    async def composer(detail, candidate):
        return deterministic_intro(detail, candidate)

    adapter = InternshalaAdapter(receipts_root=tmp_path, settle_ms=10, jitter=(0, 0), composer=composer,
                                 confirm_timeout_s=3)
    site.add(INTERNSHALA_JOB, html(
        '<a href="/student/dashboard">Dashboard</a><h1>Python Developer</h1><div class="company_name">Acme</div>'
        '<div class="internship_details">Python Django. Posted 3 days ago. 120 applicants</div>'
        f'<button onclick="location.href=\'{INTERNSHALA_FORM}\'">Apply now</button>'))
    site.add(INTERNSHALA_FORM, html("""
      <form action="/application/submitted" method="get">
        <label for="cover">Why should you be hired for this role? *</label><textarea id="cover" name="cover" required></textarea>
        <fieldset><legend>Confirm your availability *</legend>
          <label><input type="radio" name="avail" value="yes" required>Yes, I am available to join immediately</label>
          <label><input type="radio" name="avail" value="no">No (Please specify your availability)</label>
        </fieldset>
        <button type="submit">Submit</button>
      </form>"""))
    site.add("https://internshala.com/application/submitted", html("<h2>Application submitted successfully</h2>"))
    listing = JobListing(platform="internshala", external_job_id="1234567", url=INTERNSHALA_JOB)
    detail = await adapter.inspect_job(page, listing)
    assert detail.applicants.minimum == 120 and detail.posted_age_days == 3 and detail.apply_mode == "direct"
    first = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert first.state is S.WAITING_FOR_USER and first.question.prompt == "Confirm your availability"
    assert first.answers[0]["source"] == "composer" and first.clicked_apply
    detail = await adapter.inspect_job(page, listing)
    answer = {"Confirm your availability": "No (Please specify your availability)"}
    second = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers=answer)
    assert second.state is S.APPLIED, second
    submitted = site.hits[-1]
    assert "avail=no" in submitted and "cover=Hi+Acme+team" in submitted


async def modal_portal(web, tmp_path, adapter_cls, job_url, note_label, send_text):
    page, site = web

    async def composer(detail, candidate):
        return deterministic_intro(detail, candidate)

    adapter = adapter_cls(receipts_root=tmp_path, settle_ms=10, jitter=(0, 0), composer=composer, confirm_timeout_s=3)
    site.add(job_url, html(f"""
      <a href="/profile">Me</a><a href="/application">My applications</a><a href="/jobs/applications">Applications</a>
      <h1>Founding Backend Engineer</h1><div class="startup-name"><a>Acme</a></div>
      <div class="job-description">Python, Postgres. Posted 1 day ago.</div>
      <button id="apply">Apply</button>
      <div id="m" role="dialog" style="display:none">
        <label for="note">{note_label}</label><textarea id="note" required></textarea>
        <button id="go">{send_text}</button>
      </div><div id="t"></div>
      <script>
        document.getElementById('apply').onclick = () => document.getElementById('m').style.display = 'block';
        document.getElementById('go').onclick = () => {{
          if (!document.getElementById('note').value) return;
          document.getElementById('m').style.display = 'none';
          document.getElementById('t').innerText = 'Application sent';
        }};
      </script>"""))
    listing = JobListing(platform=adapter.platform, external_job_id="65432", url=job_url)
    detail = await adapter.inspect_job(page, listing)
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.reason == "confirmed", result
    assert result.receipt["source"].startswith("confirmation_text") and result.answers[0]["source"] == "composer"
    note = await page.evaluate("document.getElementById('note').value")
    assert note.startswith("Hi Acme team") and "Python" in note and "candidate@example.com" not in note
    return result


async def test_wellfound_note_modal(web, tmp_path):
    await modal_portal(web, tmp_path, WellfoundAdapter, "https://wellfound.com/jobs/3456789-founding-backend-engineer",
                       "Write a note to Acme *", "Send application")


async def test_work_at_a_startup_founder_note(web, tmp_path):
    await modal_portal(web, tmp_path, WorkAtAStartupAdapter, "https://www.workatastartup.com/jobs/65432",
                       "Add a short note to the founders *", "Send")


async def test_wellfound_challenge_isolated_as_auth_required(web, tmp_path):
    page, site = web
    adapter = WellfoundAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0))
    site.add("https://wellfound.com/jobs", html("<h1>Verify you are human</h1>"))
    session = await adapter.check_session(page)
    assert session.status.value == "AUTH_REQUIRED" and session.reason == "challenge"


async def test_work_at_a_startup_login_host_is_auth_required(web, tmp_path):
    page, site = web
    adapter = WorkAtAStartupAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0))
    site.add("https://www.workatastartup.com/application",
             html("<script>location.href='https://account.ycombinator.com/?continue=x'</script>"))
    site.add("https://account.ycombinator.com", html('<input id="ycid-input"><input type="password">'))
    session = await adapter.check_session(page)
    assert session.status.value == "AUTH_REQUIRED" and session.reason == "login"


# --- Naukri live OTP entry ---------------------------------------------------------------------------------
OTP_PAGE = html("""
  <div id="box"><input id="otp" name="otp" maxlength="6"><button id="v">Verify</button></div><p id="msg"></p>
  <script>
    document.getElementById('v').onclick = () => {
      if (document.getElementById('otp').value === '482913') document.getElementById('box').remove();
      else document.getElementById('msg').innerText = 'Invalid OTP, please try again';
    };
  </script>""")
SPLIT_OTP_PAGE = html("""
  <div id="box">""" + "".join(f'<input class="otp-digit" name="otp{i}" maxlength="1">' for i in range(6)) + """
  <button id="v">Verify</button></div>
  <script>
    document.getElementById('v').onclick = () => {
      const code = [...document.querySelectorAll('.otp-digit')].map(i => i.value).join('');
      if (code === '482913') document.getElementById('box').remove();
    };
  </script>""")


async def test_naukri_otp_entry_single_and_split_boxes(web):
    page, site = web
    adapter = NaukriAdapter(settle_ms=10)
    site.add("https://www.naukri.com/nlogin/login", OTP_PAGE)
    await page.goto("https://www.naukri.com/nlogin/login")
    assert await adapter.enter_otp(page, "111111") is False  # invalid code is reported, not retried
    await page.goto("https://www.naukri.com/nlogin/login")
    assert await adapter.enter_otp(page, "482913") is True
    site.add("https://www.naukri.com/nlogin/login", SPLIT_OTP_PAGE)
    await page.goto("https://www.naukri.com/nlogin/login")
    assert await adapter.enter_otp(page, "482913") is True
    assert await adapter.enter_otp(page, "not-a-code") is False


async def test_naukri_otp_sources_prefer_owner_answer_then_email():
    seen = []

    async def provider(portal, since):
        seen.append(portal)
        return "765432"

    adapter = NaukriAdapter(otp_provider=provider)
    assert NaukriAdapter.otp_from_answers({"Naukri needs OTP": "  123456 ", "Q": "Yes"}) == "123456"
    assert await adapter.obtain_otp({"Naukri needs OTP": "123456"}, NOW) == ("123456", "hitl_owner_answer")
    assert await adapter.obtain_otp({}, NOW) == ("765432", "email_otp") and seen == ["naukri"]
    assert await NaukriAdapter().obtain_otp(None, NOW) == (None, "none")


async def test_naukri_otp_challenge_recovers_then_reinspects(tmp_path):
    calls = []

    class Recovering(NaukriAdapter):
        async def recover_otp(self, page, hitl_answers):
            calls.append(("otp", dict(hitl_answers or {})))
            return True, "hitl_owner_answer"

        async def _goto(self, page, url):
            calls.append(("goto", url))

        async def inspect_job(self, page, listing):
            return JobDetail(listing=listing, applicants=UNKNOWN_APPLICANTS, posted_age_days=1, already_applied=True,
                             apply_mode="applied")

    listing = JobListing(platform="naukri", external_job_id="251126000123", url="https://www.naukri.com/job-listings-x-251126000123")
    detail = JobDetail(listing=listing, applicants=UNKNOWN_APPLICANTS, posted_age_days=1, already_applied=False,
                       apply_mode="direct", challenge="otp")
    result = await Recovering().apply_job(object(), detail, facts(tmp_path), dry_run=False,
                                          hitl_answers={"Naukri needs OTP": "482913"})
    assert result.state is S.APPLIED and result.reason == "already_applied_on_portal"
    assert calls[0] == ("otp", {"Naukri needs OTP": "482913"})
    dry = await Recovering().apply_job(object(), detail, facts(tmp_path), dry_run=True)
    assert dry.state is S.WAITING_FOR_USER and dry.question.kind == "OTP"  # dry runs never type OTPs


async def test_hosted_filler_never_fills_optional_unknown_fields(web, tmp_path):
    page, site = web
    site.add("https://boards.greenhouse.io/acme/jobs/9", html("""
      <label for="ref">How did you hear about us?</label><input id="ref">
      <label for="race">Race</label><select id="race"><option value="">--</option><option>Decline</option></select>"""))
    await page.goto("https://boards.greenhouse.io/acme/jobs/9")
    outcome = await HostedFormFiller(jitter=(0, 0)).fill(page, gh_detail(), facts(tmp_path))
    assert outcome.filled == [] and outcome.question is None
    assert await page.evaluate("document.getElementById('ref').value") == ""


def test_shared_applier_has_no_send_or_delete_surface():
    applier = HostedAtsApplier()
    assert not [n for n in dir(applier) if any(w in n for w in ("send", "delete", "replay"))]
    assert json.dumps(sorted(PORTALS)) and datetime.now(UTC)
