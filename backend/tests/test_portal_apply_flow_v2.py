"""Phase 8 portal apply-flow fixes (synthetic pages, real headless Chromium, no network).

- Naukri `apply_control_changed`: hidden sticky/pre-hydration Apply copies no longer count;
  hydration swaps (Apply -> company site / Applied) are re-classified, not failed.
- Interactive portals (Instahyre/YC/Wellfound/Internshala): duplicate CTAs with the same
  action are one control; closed roles and "log in to apply" are classified.
- Unknown posting age: the job page's JSON-LD datePosted fills it when the card had none.
- Smart external ATS handoff: Greenhouse/Lever links become DISCOVERED rows for those
  adapters (deduped by ATS job id); other external sites stay `external_company_site`.
- Worker fairness: round-robin start + bounded per-portal backoff.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.adapters.common import ats_handoff_target
from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.adapters.work_at_a_startup import WorkAtAStartupAdapter
from backend.app.browser_v2.rules import PortalRules, parse_applicants
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.worker import Worker
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    facts,
    html,
    web_fixture,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

FAST: dict[str, Any] = {"settle_ms": 10, "refresh_wait_ms": 10, "jitter": (0, 0)}
NAUKRI_JOB = "https://www.naukri.com/job-listings-backend-engineer-acme-bengaluru-3-to-5-years-261125500123"
NOON_IST = datetime(2026, 11, 26, 6, 30, tzinfo=UTC)


def naukri_page(header_buttons: str, extra: str = "", script: str = "") -> str:
    return html(f"""
      <nav class="nI-gNb-drawer"><a href="/mnjuser/profile">Profile</a></nav>
      <section id="job_header"><h1>Backend Engineer</h1>
        <div class="styles_jd-header-comp-name"><a>Acme</a></div>
        <span>Posted: 2 days ago</span><span>Applicants: 40</span>
        <div class="actions">{header_buttons}</div></section>
      {extra}
      <section class="styles_job-desc-container">Python FastAPI PostgreSQL backend role</section>
      {script}""", title="Backend Engineer - Acme - Naukri")


def naukri_listing() -> JobListing:
    return JobListing(platform="naukri", external_job_id="261125500123", url=NAUKRI_JOB,
                      title="Backend Engineer", company="Acme", posted_age_days=2)


async def naukri_dry_run(web, tmp_path, body: str):
    page, site = web
    site.add(NAUKRI_JOB, body)
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    return detail, result


class TestNaukriApplyControl:
    async def test_hidden_sticky_copy_no_longer_causes_apply_control_changed(self, web, tmp_path):
        # Live shape: a second jd-header (sticky, display:none until scroll) repeats the Apply button.
        sticky = ('<div class="styles_jd-header-sticky" style="display:none"><h1>Backend Engineer</h1>'
                  '<button>Apply</button></div>')
        detail, result = await naukri_dry_run(web, tmp_path, naukri_page("<button>Apply</button>", sticky))
        assert detail.apply_mode == "direct"
        assert result.reason == "dry_run_stopped_before_apply_click" and result.state is S.SCORED

    async def test_hydration_swap_to_company_site_is_external_not_failed(self, web, tmp_path):
        swap = """<script>setTimeout(() => { const b = document.querySelector('#job_header button');
                   b.textContent = 'Apply on company site'; }, 120);</script>"""
        _detail, result = await naukri_dry_run(web, tmp_path, naukri_page("<button>Apply</button>", script=swap))
        assert result.state is S.FILTERED_OUT and result.reason == "external_company_site"

    async def test_hydration_reveals_applied_badge(self, web, tmp_path):
        swap = """<script>setTimeout(() => { document.querySelector('#job_header button').textContent = 'Applied';
                   }, 120);</script>"""
        _, result = await naukri_dry_run(web, tmp_path, naukri_page("<button>Apply</button>", script=swap))
        assert result.state is S.APPLIED and result.reason == "already_applied_on_portal"

    async def test_two_visible_apply_buttons_still_fail_closed(self, web, tmp_path):
        page, site = web
        site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>"))
        adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "n")
        detail = await adapter.inspect_job(page, naukri_listing())
        await page.evaluate("() => document.querySelector('#job_header .actions').insertAdjacentHTML("
                            "'beforeend', '<button>Apply</button>')")
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert result.state is S.FAILED and result.reason == "apply_control_changed"

    async def test_expired_job_is_closed_not_failed(self, web, tmp_path):
        body = naukri_page("", extra="<div>This job is no longer available</div>")
        detail, result = await naukri_dry_run(web, tmp_path, body)
        assert detail.apply_mode == "closed"
        assert result.state is S.FILTERED_OUT and result.reason == "job_closed"


INSTAHYRE_JOB = "https://www.instahyre.com/job-412345-backend-engineer-at-acme-bangalore/"
LOGGED_NAV = '<nav id="candidate-nav"><a href="/candidate/profile">Me</a><a href="/logout">Out</a></nav>'


class TestInteractiveApplyControl:
    async def test_same_action_duplicates_count_once(self, web, tmp_path):
        page, site = web
        site.add(INSTAHYRE_JOB, html(LOGGED_NAV + """
          <main><h1>Backend Engineer</h1><p class="company-name">Acme</p>
            <button ng-click="openApplyModal(job)">Apply</button>
            <div class="description">Python FastAPI backend services</div>
            <div class="sticky-footer"><button ng-click="openApplyModal(job)">Apply</button></div></main>"""))
        adapter = InstahyreAdapter(**FAST)
        listing = JobListing(platform="instahyre", external_job_id="412345", url=INSTAHYRE_JOB,
                             title="Backend Engineer", company="Acme")
        detail = await adapter.inspect_job(page, listing)
        assert detail.apply_mode == "direct"
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert result.reason == "dry_run_stopped_before_apply_click"

    async def test_different_actions_stay_ambiguous(self, web, tmp_path):
        page, site = web
        site.add(INSTAHYRE_JOB, html(LOGGED_NAV + """
          <main><h1>Backend Engineer</h1><button ng-click="openApplyModal(job)">Apply</button>
            <button ng-click="interested(job)">I'm interested</button></main>"""))
        detail = await InstahyreAdapter(**FAST).inspect_job(page, JobListing(
            platform="instahyre", external_job_id="412345", url=INSTAHYRE_JOB))
        assert detail.apply_mode == "ambiguous"

    async def test_json_ld_date_posted_fills_unknown_card_age(self, web, tmp_path):
        page, site = web
        posted = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d")
        site.add(INSTAHYRE_JOB, html(LOGGED_NAV + f"""
          <script type="application/ld+json">{{"@context": "https://schema.org", "@type": "JobPosting",
            "title": "Backend Engineer", "datePosted": "{posted}"}}</script>
          <main><h1>Backend Engineer</h1><button ng-click="openApplyModal(job)">Apply</button></main>"""))
        listing = JobListing(platform="instahyre", external_job_id="412345", url=INSTAHYRE_JOB,
                             posted_age_days=None)
        detail = await InstahyreAdapter(**FAST).inspect_job(page, listing)
        assert detail.posted_age_days == 3

    async def test_closed_yc_role_is_filtered_and_login_to_apply_is_auth(self, web, tmp_path):
        page, site = web
        url = "https://www.workatastartup.com/jobs/77123"
        site.add(url, html('<a href="/application">Dashboard</a><main><h1>Founding Engineer</h1>'
                           "<p>This role is no longer accepting applications.</p></main>"))
        adapter = WorkAtAStartupAdapter(**FAST)
        listing = JobListing(platform="work_at_a_startup", external_job_id="77123", url=url)
        detail = await adapter.inspect_job(page, listing)
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert detail.apply_mode == "closed" and result.state is S.FILTERED_OUT and result.reason == "job_closed"
        site.add(url, html("<main><h1>Founding Engineer</h1><p>Log in to apply to this role.</p></main>"))
        detail = await adapter.inspect_job(page, listing)
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert detail.challenge == "login" and result.state is S.WAITING_FOR_USER
        assert result.question is not None and result.question.kind == "AUTH"


# --- smart external ATS handoff ------------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/4012345", ("greenhouse", "4012345", "acme", False)),
    ("https://job-boards.greenhouse.io/acme/jobs/4012345?gh_src=x", ("greenhouse", "4012345", "acme", False)),
    ("https://job-boards.greenhouse.io/embed/job_app?for=acme&token=4012345", ("greenhouse", "4012345", "acme", False)),
    ("https://stripe.com/jobs/search?gh_jid=6123456", ("greenhouse", "6123456", "stripe", True)),
    ("https://careers.acme.io/open-roles?gh_jid=77", ("greenhouse", "77", "acme", True)),
    ("https://jobs.lever.co/spotify/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab/apply",
     ("lever", "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab", "spotify", False)),
])
def test_ats_handoff_targets(url, expected):
    target = ats_handoff_target(url)
    assert target is not None
    assert (target.platform, target.external_job_id, target.board, target.board_guessed) == expected


@pytest.mark.parametrize("url", [
    "https://acme.workday.com/jobs/123", "http://boards.greenhouse.io/acme/jobs/1",
    "https://boards.greenhouse.io/acme", "https://jobs.lever.co/spotify", None,
    "https://example.com/careers?gh_jid=abc",
])
def test_unsupported_external_sites_are_not_handed_off(url):
    assert ats_handoff_target(url) is None


class FakeManager:
    running = True

    @asynccontextmanager
    async def job(self):
        yield object()

    async def maybe_recycle_between_jobs(self, max_age_sec: int = 10800) -> bool:
        return False

    async def close(self) -> None:
        self.running = False


class ExternalAdapter:
    """Wellfound-like portal whose Apply leads to an employer ATS."""

    def __init__(self, platform: str, apply_url: str | None) -> None:
        self.platform = platform
        self.apply_url = apply_url
        self.applied = 0

    async def check_session(self, page):
        return SessionCheck(AuthStatus.OK)

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        return [JobListing(platform=self.platform, external_job_id="w1", url="https://wellfound.com/jobs/1",
                           title="Backend Engineer", company="Acme", posted_age_days=1)]

    async def inspect_job(self, page, listing):
        return JobDetail(listing=listing, applicants=parse_applicants("10 applicants"), posted_age_days=1,
                         already_applied=False, apply_mode="external", description="python fastapi backend",
                         apply_url=self.apply_url)

    async def extract_form(self, page):
        return {}

    async def detect_portal_limit(self, page):
        return None

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        self.applied += 1
        return ApplyResult(S.FILTERED_OUT, "external_company_site", dry_run)


def store_for(*platforms: str) -> MemoryStore:
    rules = {p: PortalRules(platform=p, enabled=True, auto_apply_enabled=True, active_hours_start=None,
                            active_hours_end=None) for p in platforms}
    return MemoryStore(rules=rules, profile={"preferences": {"target_roles": ["Backend Engineer"]}},
                       worker=WorkerControl(desired_state=WorkerState.RUNNING, dry_run=False))


async def test_greenhouse_link_is_handed_off_once_and_source_closed():
    store = store_for("wellfound", "greenhouse", "work_at_a_startup")
    source = ExternalAdapter("wellfound", "https://job-boards.greenhouse.io/acme/jobs/4012345")
    service = BrowserService(FakeManager(), store, adapters={"wellfound": source,  # type: ignore[arg-type]
                                                             "greenhouse": ExternalAdapter("greenhouse", None)})
    listing = (await source.discover_jobs(None, query="x"))[0]
    outcome = await service.process_job(listing, dry_run=False, record_filters=True)
    assert outcome["reason"] == "ats_handoff:greenhouse:4012345" and outcome["handoff_recorded"]
    queued = await store.get("greenhouse", "4012345")
    assert queued is not None and queued.state is S.DISCOVERED
    assert queued.job_url == "https://job-boards.greenhouse.io/acme/jobs/4012345" and queued.company_name == "Acme"
    source_row = await store.get("wellfound", "w1")
    assert source_row is not None and source_row.state is S.FILTERED_OUT and source.applied == 0
    # a second portal pointing at the same posting is deduped by the ATS job id
    other = ExternalAdapter("work_at_a_startup", "https://boards.greenhouse.io/acme/jobs/4012345")
    service.adapters["work_at_a_startup"] = other
    again = await service.process_job(JobListing(platform="work_at_a_startup", external_job_id="y9",
                                                 url="https://www.workatastartup.com/jobs/9", title="Backend Engineer",
                                                 company="Acme Labs Two", posted_age_days=1),
                                      dry_run=False, record_filters=True)
    assert again["handoff"]["state"] == "DISCOVERED"
    assert sum(1 for (p, _), _r in store.records.items() if p == "greenhouse") == 1


async def test_unsupported_external_site_still_terminates_cleanly():
    store = store_for("wellfound")
    source = ExternalAdapter("wellfound", "https://acme.myworkdayjobs.com/en-US/careers/job/123")
    service = BrowserService(FakeManager(), store, adapters={"wellfound": source})  # type: ignore[arg-type]
    listing = (await source.discover_jobs(None, query="x"))[0]
    outcome = await service.process_job(listing, dry_run=False, record_filters=True)
    assert outcome["reason"] == "external_company_site" and "handoff" not in outcome
    closed = await store.get("wellfound", "w1")
    assert closed is not None and closed.state is S.FILTERED_OUT


async def test_dry_run_reports_handoff_without_writing():
    store = store_for("wellfound", "lever")
    source = ExternalAdapter("wellfound", "https://jobs.lever.co/spotify/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab")
    service = BrowserService(FakeManager(), store, adapters={"wellfound": source,  # type: ignore[arg-type]
                                                             "lever": ExternalAdapter("lever", None)})
    listing = (await source.discover_jobs(None, query="x"))[0]
    outcome = await service.process_job(listing, dry_run=True, record_filters=False)
    assert outcome["handoff"]["platform"] == "lever" and outcome["handoff_recorded"] is False
    assert await store.get("lever", "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab") is None


# --- worker fairness + backoff -------------------------------------------------------------------
class TimeoutPortal(ExternalAdapter):
    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        raise TimeoutError("page.goto: Timeout 45000ms exceeded")


async def test_round_robin_start_and_bounded_backoff_isolate_a_failing_portal():
    store = store_for("instahyre", "naukri", "wellfound")
    adapters = {"instahyre": TimeoutPortal("instahyre", None), "naukri": ExternalAdapter("naukri", None),
                "wellfound": ExternalAdapter("wellfound", None)}
    clock = {"now": NOON_IST}

    async def no_sleep(_seconds):
        return None

    service = BrowserService(FakeManager(), store, adapters=adapters)  # type: ignore[arg-type]
    worker = Worker(service, clock=lambda: clock["now"], sleeper=no_sleep, idle_poll_sec=5)
    first = await worker.cycle()
    second = await worker.cycle()
    assert [p.platform for p in first.portals] == ["instahyre", "naukri", "wellfound"]
    assert [p.platform for p in second.portals] == ["naukri", "wellfound", "instahyre"]  # rotated start
    assert first.portals[0].skipped == "error: TimeoutError"
    assert (second.portals[2].skipped or "").startswith("backoff_until:")  # failing portal waits, others ran
    assert second.portals[0].skipped is None and second.portals[1].skipped is None
    failures, until = worker.portal_backoff["instahyre"]
    assert failures == 1 and until == NOON_IST + timedelta(minutes=5)
    clock["now"] = NOON_IST + timedelta(minutes=6)
    await worker.cycle()
    failures, until = worker.portal_backoff["instahyre"]
    assert failures == 2 and until == clock["now"] + timedelta(minutes=10)  # exponential, capped at 60 min
    for _ in range(6):
        clock["now"] = until + timedelta(seconds=1)
        await worker.cycle()
        failures, until = worker.portal_backoff["instahyre"]
    assert until - clock["now"] <= timedelta(hours=1)


# --- Naukri chatbot questionnaire (synthetic page; the "submission" never leaves Chromium) ----------
CHATBOT_SCRIPT = """<script>
const steps = [
  {q: "Which of these have you used in production?", html: `
     <label for="c1">Python</label><input type="checkbox" id="c1">
     <label for="c2">Java</label><input type="checkbox" id="c2">
     <label for="c3">Go</label><input type="checkbox" id="c3">`},
  {q: "Select your notice period", html: `<select><option value="">Select</option>
     <option value="0">Immediate</option><option value="30">1 Month</option></select>`},
  {q: "Are you willing to relocate to Pune?", html: `
     <input class="ssrc__radio" type="radio" id="r1" value="Yes"><label class="ssrc__label" for="r1">Yes</label>
     <input class="ssrc__radio" type="radio" id="r2" value="No"><label class="ssrc__label" for="r2">No</label>`},
  {q: "Why do you want to join Acme?", html: `<div class="textArea" contenteditable="true"></div>`},
];
let i = -1;
window.answers = [];
function render() {
  const d = document.querySelector('.chatbot_DrawerContentWrapper');
  if (i >= steps.length) { d.remove(); document.body.insertAdjacentHTML('beforeend',
      '<div class="apply-message">You have successfully applied to Backend Engineer</div>'); return; }
  d.innerHTML = `<div class="chatbot_MessageContainer"><div class="botItem"><div class="botMsg">${steps[i].q}</div></div></div>
    <div class="controls">${steps[i].html}</div><div class="send">Save</div>`;
  d.querySelector('.send').onclick = () => {
    const picked = [...d.querySelectorAll('input:checked')].map(x => x.id);
    const sel = d.querySelector('select');
    const ed = d.querySelector('.textArea');
    window.answers.push({step: i, picked, select: sel && sel.value, text: ed && ed.innerText});
    i += 1; setTimeout(render, 50);
  };
}
document.querySelector('#job_header button').onclick = () => {
  document.body.insertAdjacentHTML('beforeend', '<div class="chatbot_DrawerContentWrapper"></div>');
  i = 0; setTimeout(render, 50);
};
</script>"""


async def test_naukri_questionnaire_checkbox_dropdown_radio_text_then_receipt(web, tmp_path):
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=CHATBOT_SCRIPT))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    owner = {"Which of these have you used in production?": "Python, Go",
             "Select your notice period": "1 Month",
             "Are you willing to relocate to Pune?": "Yes",
             "Why do you want to join Acme?": "I build Python backends."}
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers=owner)
    assert result.state is S.APPLIED and result.reason == "confirmed"
    assert result.receipt is not None and result.receipt["source"].startswith("success_text")
    recorded = await page.evaluate("() => window.answers")
    assert recorded[0]["picked"] == ["c1", "c3"] and recorded[1]["select"] == "30"
    assert recorded[2]["picked"] == ["r1"] and recorded[3]["text"] == "I build Python backends."
    assert [a["source"] for a in result.answers] == ["human_hitl"] * 4


async def test_naukri_multi_select_without_answer_asks_owner_with_multi_kind(web, tmp_path):
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=CHATBOT_SCRIPT))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers={})
    assert result.state is S.WAITING_FOR_USER and result.question is not None
    assert result.question.input_kind == "multi" and result.question.options == ("Python", "Java", "Go")


# --- live 2026-11-26 Phase 8 dry-run regressions ------------------------------------------------
async def test_instahyre_anchor_wrapping_the_apply_button_is_one_control(web, tmp_path):
    page, site = web
    site.add(INSTAHYRE_JOB, html(LOGGED_NAV + """
      <main><h1>SDE 1 - Fullstack</h1><h2>at Writesonic</h2>
        <div class="apply-button ng-scope"><a class="text-center ng-scope">
          <button class="btn-filled btn-md" ng-click="submitChoice(opp, true)">Apply now</button></a></div>
        <div class="description">Python FastAPI services</div></main>"""))
    adapter = InstahyreAdapter(**FAST)
    detail = await adapter.inspect_job(page, JobListing(platform="instahyre", external_job_id="412345",
                                                        url=INSTAHYRE_JOB, title="SDE 1 - Fullstack"))
    assert detail.apply_mode == "direct"
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    assert result.reason == "dry_run_stopped_before_apply_click"


async def test_internshala_other_candidates_applied_text_is_not_our_application(web, tmp_path):
    from backend.app.browser_v2.adapters.internshala import InternshalaAdapter

    page, site = web
    url = "https://internshala.com/internship/detail/software-engineer-internship-in-roorkee-at-acme1795176260"
    site.add(url, html("""<main><h1>Software Engineer Internship</h1>
      <p>150+ candidates have already applied. Increase your profile visibility to get noticed</p>
      <div class="buttons_container"><button class="btn btn-primary detail_page_bottom apply_now_btn">Apply now</button></div>
      </main>"""))
    adapter = InternshalaAdapter(**FAST)
    detail = await adapter.inspect_job(page, JobListing(platform="internshala", external_job_id="1795176260", url=url))
    assert detail.already_applied is False and detail.apply_mode == "direct"
    site.add(url, html("<main><h1>Software Engineer Internship</h1><p>You have already applied to this internship.</p></main>"))
    detail = await adapter.inspect_job(page, JobListing(platform="internshala", external_job_id="1795176260", url=url))
    assert detail.already_applied is True


async def test_wellfound_action_bar_apply_is_primary_over_bottom_apply_now(web, tmp_path):
    from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter

    page, site = web
    url = "https://wellfound.com/jobs/4372312-software-engineer"
    site.add(url, html("""<nav><a href="/jobs/applications">Applied</a></nav>
      <main><h1>Software Engineer</h1><div class="styles_actionBar__jZgoT"><button>Save</button>
        <button class="styles_component__O1">Apply</button></div>
        <div class="styles_content__iLhPF"><p>Python</p><button class="styles_component__O1">Apply now</button></div></main>"""))
    adapter = WellfoundAdapter(**FAST)
    detail = await adapter.inspect_job(page, JobListing(platform="wellfound", external_job_id="4372312", url=url))
    assert detail.apply_mode == "direct" and detail.already_applied is False
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    assert result.reason == "dry_run_stopped_before_apply_click"
    assert await page.evaluate("() => document.querySelector('[data-aa-apply]').innerText") == "Apply"


async def test_yc_status_menu_is_classified_unsupported_not_none(web, tmp_path):
    page, site = web
    url = "https://www.workatastartup.com/jobs/97103"
    site.add(url, html('<a href="/application">Dashboard</a><main><h1>Engineering, Product at telli</h1>'
                       '<a href="#">Change status to apply</a><button>Save job</button></main>'))
    adapter = WorkAtAStartupAdapter(**FAST)
    detail = await adapter.inspect_job(page, JobListing(platform="work_at_a_startup", external_job_id="97103", url=url))
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    assert detail.apply_mode == "unsupported_ui"
    assert result.state is S.FAILED and result.reason == "apply_control_unsupported_ui"


async def test_combobox_options_ignore_the_phone_country_picker(web, tmp_path):
    from backend.app.browser_v2.adapters.common import HostedFormFiller

    page, site = web
    url = "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=4012345"
    site.add(url, html("""
      <ul class="iti__country-list" role="listbox"><li role="option">Afghanistan+93</li><li role="option">India+91</li></ul>
      <label for="q1">Are you currently based in Bangalore?</label>
      <input id="q1" role="combobox" aria-controls="q1-list" data-aa-field="7">
      <ul id="q1-list" role="listbox" hidden><li role="option">Yes</li><li role="option">No</li></ul>
      <label for="q2">How did you hear about us?</label><input id="q2" role="combobox" data-aa-field="8">
      <ul id="q2-list" role="listbox" hidden><li role="option">LinkedIn</li><li role="option">Friend</li></ul>
      <script>
        for (const [box, list] of [["q1", "q1-list"], ["q2", "q2-list"]]) {
          const el = document.getElementById(box), ul = document.getElementById(list);
          el.addEventListener("click", () => { ul.hidden = false; });
          el.addEventListener("keydown", (e) => { if (e.key === "Escape") ul.hidden = true; });
        }
      </script>"""))
    await page.goto(url)
    filler = HostedFormFiller()
    filler.settle_ms = 50
    assert await filler._combobox_options(page, {"idx": 7}) == ("Yes", "No")  # aria-controls scoped
    assert await filler._combobox_options(page, {"idx": 8}) == ("LinkedIn", "Friend")  # newly visible only


async def test_naukri_cold_load_waits_for_the_react_header(web, tmp_path):
    """Live canary 2026-11-27: inspection ran before the JD header rendered -> no title/age/JD ->
    needs_review. The adapter now waits for the rendered header."""
    page, site = web
    late = naukri_page("<button>Apply</button>")
    body_start = late.index("<body>") + len("<body>")
    deferred = (late[:body_start] + "<div id='app'></div><template id='t'>" + late[body_start:].replace(
        "</body>", "") + "</template><script>setTimeout(() => { document.getElementById('app').innerHTML = "
        "document.getElementById('t').innerHTML; }, 700);</script></body></html>")
    site.add(NAUKRI_JOB, deferred)
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, JobListing(platform="naukri", external_job_id="261125500123",
                                                        url=NAUKRI_JOB))
    assert detail.listing.title == "Backend Engineer" and detail.posted_age_days == 2
    assert detail.description and "FastAPI" in detail.description and detail.apply_mode == "direct"


# --- Phase 8b: required-experience filter (live canary found 4-5 yr roles passing for a <1 yr profile) ----
@pytest.mark.parametrize("text,expected", [
    ("0 - 5 years", (0.0, 5.0)), ("4-5 Yrs", (4.0, 5.0)), ("3+ years", (3.0, None)), ("Fresher", (0.0, 1.0)),
    ("2 to 6 years", (2.0, 6.0)), (None, (None, None)), ("Not disclosed", (None, None)),
])
def test_parse_experience_range(text, expected):
    from backend.app.browser_v2.rules import parse_experience_range

    assert parse_experience_range(text) == expected


def test_experience_filter_uses_minimum_with_one_year_tolerance():
    from backend.app.browser_v2.rules import (
        CandidatePreferences,
        Decision,
        evaluate_pipeline,
    )

    rules = PortalRules(platform="naukri", enabled=True)
    prefs = CandidatePreferences.from_profile({"preferences": {"total_experience_years": 0.5}})
    run = lambda text: evaluate_pipeline(age_days=1, applicants=parse_applicants("20 applicants"),
                                         rules=rules, prefs=prefs, title="Backend Engineer", company="Acme",
                                         require_description=False, experience_text=text)
    senior = run("4 - 5 years")
    assert senior.decision is Decision.FILTERED and senior.reasons[0].startswith("experience_above_profile")
    assert run("0 - 5 years").decision is Decision.PASS and run("1-3 Yrs").decision is Decision.PASS
    assert run(None).decision is Decision.PASS  # unknown requirement never blocks
    unknown_profile = CandidatePreferences.from_profile({"preferences": {}})
    assert unknown_profile.experience_years is None
    assert CandidatePreferences.from_profile({"verified_experience_years": 2}).experience_years == 2.0


async def test_naukri_reads_required_experience_from_the_header(web, tmp_path):
    page, site = web
    body = naukri_page("<button>Apply</button>").replace(
        "<span>Posted: 2 days ago</span>", "<span>4 - 5 years</span><span>Posted: 2 days ago</span>")
    site.add(NAUKRI_JOB, body)
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    assert detail.listing.experience_text == "4 - 5 years"


def test_owner_answers_match_options_regardless_of_punctuation():
    from backend.app.browser_v2.answers import match_option

    options = ("Applied / In Progress", "Yes, I have", "No, I dont have one", "I am not sure")
    assert match_option("No, I don't have one", options) == "No, I dont have one"
    assert match_option("no i dont have one!", options) == "No, I dont have one"
    assert match_option("No", options) is None  # still never a guess
    assert match_option("Applied In Progress", options) == "Applied / In Progress"


LIVE_DRAWER_SCRIPT = """<script>
window.answers = [];
document.querySelector('#job_header button').onclick = () => {
  document.body.insertAdjacentHTML('beforeend', `<div class="chatbot_DrawerContentWrapper">
    <input class="chatbot_Uploader" type="file" style="display:none">
    <div class="chatbot_MessageContainer"><div class="botItem"><div class="botMsg">Hi karan, thank you for showing interest.</div></div></div></div>`);
  setTimeout(() => {
    const d = document.querySelector('.chatbot_DrawerContentWrapper');
    d.querySelector('.chatbot_MessageContainer').insertAdjacentHTML('beforeend',
      '<div class="botItem"><div class="botMsg">Do you have a digitally signed and verified resume issued by any company or organization?</div></div>');
    d.insertAdjacentHTML('beforeend', `
      <input class="ssrc__radio" type="radio" id="r1" value="Yes, I have"><label class="ssrc__label" for="r1">Yes, I have</label>
      <input class="ssrc__radio" type="radio" id="r2" value="No, I dont have one"><label class="ssrc__label" for="r2">No, I don't have one</label>
      <div class="send">Save</div>`);
    d.querySelector('.send').onclick = () => {
      window.answers.push([...d.querySelectorAll('input:checked')].map(x => x.id));
      d.remove();
      document.body.insertAdjacentHTML('beforeend', '<div>You have successfully applied to Software Engineer</div>');
    };
  }, 400);
};
</script>"""


async def test_naukri_live_drawer_hidden_uploader_and_apostrophe_label(web, tmp_path):
    """Live canary 2026-11-27: the hidden uploader made every radio question 'file_upload', and the
    radio value ("dont") differed from its label ("don't")."""
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=LIVE_DRAWER_SCRIPT))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    question = "Do you have a digitally signed and verified resume issued by any company or organization?"
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False,
                                     hitl_answers={question: "No, I dont have one"})
    assert result.state is S.APPLIED and result.reason == "confirmed"
    assert await page.evaluate("() => window.answers") == [["r2"]]
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=LIVE_DRAWER_SCRIPT))
    detail = await adapter.inspect_job(page, naukri_listing())
    unanswered = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers={})
    assert unanswered.question is not None and unanswered.question.input_kind == "choice"
    assert unanswered.question.prompt == question and "No, I dont have one" in unanswered.question.options


def optional_drawer(second_question: str) -> str:
    return """<script>
window.answers = [];
document.querySelector('#job_header button').onclick = () => {
  document.body.insertAdjacentHTML('beforeend', '<div class="chatbot_DrawerContentWrapper">' +
    '<input class="chatbot_Uploader" type="file" style="display:none"><div class="chatbot_MessageContainer"></div><div class="ctl"></div></div>');
  const d = document.querySelector('.chatbot_DrawerContentWrapper');
  const ask = (q, html) => { d.querySelector('.chatbot_MessageContainer').insertAdjacentHTML('beforeend',
      `<div class="botItem"><div class="botMsg">${q}</div></div>`); d.querySelector('.ctl').innerHTML = html; };
  ask("Do you have a digitally signed and verified resume issued by any company or organization?",
      `<input class="ssrc__radio" type="radio" id="r2" value="No, I dont have one"><label class="ssrc__label" for="r2">No, I don't have one</label><div class="send">Save</div>`);
  d.querySelector('.send').onclick = () => {
    window.answers.push('radio');
    setTimeout(() => {
      ask("SECOND_Q", `<div class="textArea" contenteditable="true"></div><div class="chipsContainer"><span class="chatbot_Chip">Skip this question</span></div><div class="send">Save</div>`);
      d.querySelector('.chatbot_Chip').onclick = () => { window.answers.push('skipped'); d.remove();
        document.body.insertAdjacentHTML('beforeend', '<div>You have successfully applied to Software Engineer</div>'); };
    }, 300);
  };
};
</script>""".replace("SECOND_Q", second_question)


async def test_naukri_skips_optional_unknown_questions_but_asks_required_ones(web, tmp_path):
    page, site = web
    owner = {"Do you have a digitally signed and verified resume issued by any company or organization?":
             "No, I dont have one"}
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=optional_drawer(
        "Enter Resume Verification ID and/or Verification URL. (if available)")))
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers=owner)
    assert result.state is S.APPLIED and await page.evaluate("() => window.answers") == ["radio", "skipped"]
    assert [a["source"] for a in result.answers] == ["human_hitl", "skip_optional"]
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=optional_drawer(
        "Describe your largest production incident")))
    detail = await adapter.inspect_job(page, naukri_listing())
    required = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False, hitl_answers=owner)
    assert required.state is S.WAITING_FOR_USER and required.question is not None
    assert required.question.prompt == "Describe your largest production incident"


# --- Phase 8b: verified reconciliation + navigation-tolerant questionnaire (live canary 2026-11-27) ----------
def test_submission_unknown_only_exits_to_applied():
    from backend.app.browser_v2.state import InvalidTransition, check_transition

    check_transition(S.SUBMISSION_UNKNOWN, S.APPLIED)
    for target in S:
        if target not in (S.APPLIED, S.SUBMISSION_UNKNOWN):
            with pytest.raises(InvalidTransition):
                check_transition(S.SUBMISSION_UNKNOWN, target)
    with pytest.raises(InvalidTransition):
        check_transition(S.APPLIED, S.SUBMISSION_UNKNOWN)


class HistoryAdapter(ExternalAdapter):
    def __init__(self, rows):
        super().__init__("naukri", None)
        self.rows = rows
        self.history_reads = 0

    async def history_rows(self, page):
        self.history_reads += 1
        return self.rows

    history_match = staticmethod(NaukriAdapter.history_match)


async def unknown_job(store, job_id, title, company, reason="exception_after_reservation:Error"):
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=job_id,
                                                      url=f"https://www.naukri.com/job-listings-x-{job_id}",
                                                      title=title, company=company))
    record = await store.transition(record, S.APPLYING, "apply_started")
    return await store.transition(record, S.SUBMISSION_UNKNOWN, reason)


async def test_reconcile_moves_only_exact_history_matches_to_applied():
    store = store_for("naukri")
    await unknown_job(store, "1", "Software Engineer", "Naineet Tech")
    await unknown_job(store, "2", "Backend Developer", "Acme")
    await unknown_job(store, "3", "Backend Developer", "QTrino", reason="migrated_historical_submitted_never_replay")
    adapter = HistoryAdapter([{"title": "Software Engineer", "company": "Naineet Tech",
                               "status": "Application sent today"},
                              {"title": "Backend Developer", "company": "Acme", "status": "Applied - draft"}])
    service = BrowserService(FakeManager(), store, adapters={"naukri": adapter})  # type: ignore[arg-type]
    results = await service.reconcile_submissions("naukri")
    assert {r["external_job_id"]: r["verified"] for r in results} == {"1": True, "2": False}
    applied = await store.get("naukri", "1")
    assert applied is not None and applied.state is S.APPLIED and applied.reason == "verified_in_portal_history"
    assert applied.receipt is not None and applied.receipt["source"] == "application_history"
    for job in ("2", "3"):
        row = await store.get("naukri", job)
        assert row is not None and row.state is S.SUBMISSION_UNKNOWN  # never guessed, migrated rows untouched
    assert await service.reconcile_submissions("naukri") == [{"external_job_id": "2", "state": "SUBMISSION_UNKNOWN",
                                                               "verified": False}]
    assert adapter.history_reads == 2


def test_history_match_needs_exactly_one_sent_row():
    rows = [{"title": "SDE", "company": "Acme", "status": "Application sent today"},
            {"title": "SDE", "company": "Acme", "status": "Application sent 2 days ago"}]
    assert NaukriAdapter.history_match(rows, "SDE", "Acme") is None  # ambiguous: two applications
    match = NaukriAdapter.history_match(rows[:1], "sde ", "ACME")
    assert match is not None and match["status"] == "Application sent today"
    assert NaukriAdapter.history_match(rows[:1], None, "Acme") is None


NAVIGATING_SCRIPT = """<script>
document.querySelector('#job_header button').onclick = () => {
  document.body.insertAdjacentHTML('beforeend', `<div class="chatbot_DrawerContentWrapper"><div class="chatbot_MessageContainer">
    <div class="botItem"><div class="botMsg">Are you willing to relocate to Pune?</div></div></div>
    <input class="ssrc__radio" type="radio" id="y" value="Yes"><label class="ssrc__label" for="y">Yes</label>
    <div class="send">Save</div></div>`);
  document.querySelector('.send').onclick = () => { location.href = '/myapply/saveApply?strJobsarr=[261125500123]'; };
};
</script>"""


async def test_naukri_last_answer_navigating_to_save_apply_is_a_confirmation(web, tmp_path):
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=NAVIGATING_SCRIPT))
    site.add("https://www.naukri.com/myapply/saveApply", html("<h2>Applied to 1 job</h2>"))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False,
                                     hitl_answers={"Are you willing to relocate to Pune?": "Yes"})
    assert result.state is S.APPLIED and result.receipt is not None
    assert result.receipt["source"] == "save_apply_page"


async def test_naukri_session_check_waits_for_a_late_logged_in_header(web, tmp_path):
    """Live 2026-11-27: the launchd worker's cold Brave read the homepage before the logged-in
    header rendered -> UNKNOWN -> Naukri skipped for the whole cycle."""
    page, site = web
    site.add("https://www.naukri.com/mnjuser/homepage", html(
        "<div id='nav'></div><script>setTimeout(() => { document.getElementById('nav').innerHTML ="
        " '<div class=\"nI-gNb-drawer\"><img class=\"nI-gNb-icon-img\"><a href=\"/mnjuser/profile\">Profile</a></div>';"
        " }, 700);</script>"))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    session = await adapter.check_session(page)
    assert session.status.value == "OK" and not session.refreshed
