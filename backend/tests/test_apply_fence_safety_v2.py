"""Never fence a job that was not submitted (live 2026-11-27 Wellfound + Internshala).

- Wellfound "Apply" opened "Applications to this job are managed outside of Wellfound -> Apply on
  website": no form, nothing sent -> FILTERED_OUT (Greenhouse/Lever link handed off), never
  SUBMISSION_UNKNOWN.
- Internshala's form page has <input type=number> "Mobile number": typing "+91-..." raised a
  Playwright Error that fenced the job forever. Number inputs now get digits (phone: national number).
- Portals whose Apply click only opens a form (`apply_opens_form`): an error or a missing form before
  any submit click is a retryable FAILED; after a submit click it still propagates (fence).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.browser_v2.adapters.base import ApplyResult, JobDetail, JobListing
from backend.app.browser_v2.adapters.internshala import InternshalaAdapter
from backend.app.browser_v2.adapters.shared.form_filler import input_value
from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
from backend.app.browser_v2.rules import parse_applicants
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    facts,
    html,
    web_fixture,
)
from backend.tests.test_portal_apply_flow_v2 import (
    ExternalAdapter,
    FakeManager,
    store_for,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

FAST: dict[str, Any] = {"settle_ms": 10, "refresh_wait_ms": 10, "jitter": (0, 0), "confirm_timeout_s": 1}
WF_URL = "https://wellfound.com/jobs/5111330-software-developer-carrier"
GH_LINK = "https://job-boards.greenhouse.io/acme/jobs/4012345"
IS_URL = "https://internshala.com/internship/detail/backend-development-internship-in-delhi-at-acme1795601297"
IS_FORM = "https://internshala.com/student/personal_details"


def wellfound_page(modal: str) -> str:
    return html(f"""<nav><a href="/jobs/applications">Applied</a></nav>
      <main><h1>Software Developer</h1><div class="styles_actionBar__jZgoT"><button>Save</button>
        <button onclick="document.getElementById('m').style.display='block'">Apply</button></div>
        <p>Python backend</p></main>
      <div id="m" style="display:none">{modal}</div>""")


EXTERNAL_MODAL = f"""<div class="ReactModal__Content" role="dialog"><h3>YOUR APPLICATION</h3>
  <p>Applications to this job are managed outside of Wellfound. Click the link below to apply on the
  company website.</p><a href="{GH_LINK}">Apply on website</a><button>Close</button></div>"""


async def wellfound_detail(page: Any, adapter: WellfoundAdapter) -> JobDetail:
    return await adapter.inspect_job(page, JobListing(platform="wellfound", external_job_id="5111330", url=WF_URL))


def test_number_inputs_get_digits_and_phone_its_national_number():
    assert input_value("number", "phone", "+91-98765-43210") == "9876543210"
    assert input_value("number", "phone", "9876543210") == "9876543210"
    assert input_value("tel", "phone", "+91-98765-43210") == "+91-98765-43210"
    assert input_value("text", "phone", "+91 98765 43210") == "+91 98765 43210"
    assert input_value("number", "notice", "30 days") == "30"


async def test_wellfound_external_modal_is_filtered_with_the_ats_link_never_fenced(web, tmp_path):
    page, site = web
    site.add(WF_URL, wellfound_page(EXTERNAL_MODAL))
    adapter = WellfoundAdapter(receipts_root=tmp_path, **FAST)
    result = await adapter.apply_job(page, await wellfound_detail(page, adapter), facts(tmp_path), dry_run=False)
    assert result.state is S.FILTERED_OUT and result.reason == "external_company_site_after_click"
    assert result.receipt == {"external_url": GH_LINK}


async def test_wellfound_apply_without_a_form_is_retryable_failed(web, tmp_path):
    page, site = web
    site.add(WF_URL, wellfound_page("<p>Something went wrong</p>"))
    adapter = WellfoundAdapter(receipts_root=tmp_path, **FAST)
    result = await adapter.apply_job(page, await wellfound_detail(page, adapter), facts(tmp_path), dry_run=False)
    assert result.state is S.FAILED and result.reason == "apply_form_not_submitted"


def internshala_pages(site: Any) -> None:
    site.add(IS_URL, html(f"""<nav><a href="/student/dashboard">Dashboard</a></nav>
      <main><h1>Backend Development Internship</h1><div class="company_name">Acme</div>
        <button id="apply_now_button" onclick="location.href='{IS_FORM}'">Apply now</button></main>"""))
    site.add(IS_FORM, html("""<form onsubmit="event.preventDefault();
        document.body.innerHTML='<h2>Application submitted successfully</h2><p id=v>'
        + document.getElementById('phone').value + '</p>';">
      <label for="phone">Mobile number *</label><input id="phone" type="number" required placeholder="Mobile number">
      <button type="submit">Submit</button></form>"""))


async def test_internshala_number_phone_is_typed_and_the_application_confirmed(web, tmp_path):
    page, site = web
    internshala_pages(site)
    adapter = InternshalaAdapter(receipts_root=tmp_path, **FAST)
    detail = await adapter.inspect_job(page, JobListing(platform="internshala", external_job_id="1795601297",
                                                        url=IS_URL))
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.reason == "confirmed"
    assert await page.evaluate("document.getElementById('v').innerText") == "0000000000"  # +910000000000


async def test_error_before_submit_is_failed_but_after_submit_still_propagates(web, tmp_path, monkeypatch):
    page, site = web
    internshala_pages(site)
    adapter = InternshalaAdapter(receipts_root=tmp_path, **FAST)
    listing = JobListing(platform="internshala", external_job_id="1795601297", url=IS_URL)

    async def broken_fill(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Locator.fill: Cannot type text")

    monkeypatch.setattr(adapter.filler, "fill", broken_fill)
    result = await adapter.apply_job(page, await adapter.inspect_job(page, listing), facts(tmp_path), dry_run=False)
    assert result.state is S.FAILED and result.reason == "apply_error_before_submit:RuntimeError"
    assert not result.clicked_apply
    monkeypatch.undo()

    async def broken_confirm(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Execution context was destroyed")

    monkeypatch.setattr(adapter, "_confirmed", broken_confirm)
    with pytest.raises(RuntimeError):  # submit clicked: the service fences it as SUBMISSION_UNKNOWN
        await adapter.apply_job(page, await adapter.inspect_job(page, listing), facts(tmp_path), dry_run=False)


class AfterClickExternal(ExternalAdapter):
    """A portal whose Apply modal points at the employer's Greenhouse page."""

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        return JobDetail(listing=listing, applicants=parse_applicants("10 applicants"), posted_age_days=1,
                         already_applied=False, apply_mode="direct", description="python fastapi backend")

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        self.applied += 1
        return ApplyResult(S.FILTERED_OUT, "external_company_site_after_click", dry_run, clicked_apply=True,
                           receipt={"external_url": self.apply_url})


async def test_after_click_greenhouse_link_is_handed_off():
    store = store_for("wellfound", "greenhouse")
    source = AfterClickExternal("wellfound", GH_LINK)
    service = BrowserService(FakeManager(), store, adapters={"wellfound": source,  # type: ignore[arg-type]
                                                             "greenhouse": ExternalAdapter("greenhouse", None)})
    listing = (await source.discover_jobs(None, query="x"))[0]
    outcome = await service.process_job(listing, dry_run=False, record_filters=True)
    assert outcome["reason"] == "ats_handoff:greenhouse:4012345" and outcome["handoff_recorded"]
    queued = await store.get("greenhouse", "4012345")
    assert queued is not None and queued.state is S.DISCOVERED
    row = await store.get("wellfound", "w1")
    assert row is not None and row.state is S.FILTERED_OUT and source.applied == 1


async def test_after_click_unsupported_link_just_closes_the_row():
    store = store_for("wellfound")
    source = AfterClickExternal("wellfound", "https://acme.myworkdayjobs.com/job/1")
    service = BrowserService(FakeManager(), store, adapters={"wellfound": source})  # type: ignore[arg-type]
    listing = (await source.discover_jobs(None, query="x"))[0]
    outcome = await service.process_job(listing, dry_run=False, record_filters=True)
    assert outcome["state"] == "FILTERED_OUT" and outcome["reason"] == "external_company_site_after_click"
    row = await store.get("wellfound", "w1")
    assert row is not None and row.state is S.FILTERED_OUT
