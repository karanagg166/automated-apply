"""Milestone 2 on a real headless Chromium with fully intercepted synthetic pages (no network):
Greenhouse emailed security code step, cascading conditional fields, pre-submit read-back,
the Ashby apply adapter and Naukri semantic-cache v2 wiring + rejection quarantine."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.app.browser_v2.adapters.ashby import AshbyAdapter
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.adapters.common import HostedFormFiller
from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.adapters.shared.form_pacing import HumanPulse
from backend.app.browser_v2.adapters.shared.security_code import owner_prompt
from backend.app.browser_v2.state import ApplicationState as S
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    facts,
    html,
    web_fixture,
)
from backend.tests.test_adapters_phase6 import AUTH_ANSWER, GH_JOB, gh_detail, gh_form
from backend.tests.test_portal_apply_flow_v2 import (
    NAUKRI_JOB,
    naukri_listing,
    naukri_page,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

VERIFY_PAGE = html("""
  <form action="/acme/jobs/4012345/confirmation" method="get">
    <p>A verification code was sent to your email. Enter the 8-character code to finish.</p>
    <label for="security_code">Security code</label><input id="security_code" name="security_code" maxlength="8">
    <button type="submit">Submit application</button>
  </form>""")


def gh_with_verify(site) -> None:
    site.add(GH_JOB, gh_form().replace("/acme/jobs/4012345/confirmation", "/acme/jobs/4012345/verify"))
    site.add(GH_JOB + "/verify", VERIFY_PAGE)
    site.add(GH_JOB + "/confirmation", html("<h2>Thank you for applying to Acme!</h2>"))


# --- Greenhouse security code ------------------------------------------------------------------------------
async def test_greenhouse_security_code_from_email_completes_the_application(web, tmp_path):
    page, site = web
    gh_with_verify(site)
    seen = []

    async def provider(company, submitted_at):
        seen.append((company, submitted_at))
        return "New2Code"

    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
    adapter.applier.security_code_provider = provider
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.APPLIED and result.reason == "confirmed" and result.clicked_apply
    assert result.receipt["security_code"] == "email_auto" and "New2Code" not in str(result.receipt)
    assert result.receipt["resume_variant_used"] == "backend"
    assert seen and seen[0][0] == "Acme"
    assert "security_code=New2Code" in site.hits[-1]


async def test_greenhouse_security_code_timeout_opens_one_p0_otp_card(web, tmp_path):
    page, site = web
    gh_with_verify(site)

    async def nothing(company, submitted_at):
        return None

    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
    adapter.applier.security_code_provider = nothing
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.WAITING_FOR_USER and result.reason == "security_code_timeout"
    assert result.question.kind == "OTP" and result.question.prompt == owner_prompt("Acme")
    assert result.question.context["priority"] == "P0" and result.clicked_apply
    assert not any("confirmation" in hit for hit in site.hits)
    # the owner's reply (same prompt) completes it on the next run
    await page.goto("about:blank")
    again = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False,
                                    hitl_answers=AUTH_ANSWER | {owner_prompt("Acme"): "Own6Code"})
    assert again.state is S.APPLIED and again.receipt["security_code"] == "owner_hitl"


# --- cascading conditional fields + read-back -------------------------------------------------------------
CASCADE_FORM = html("""
  <form id="f">
    <fieldset><legend>Will you require visa sponsorship? *</legend>
      <label><input type="radio" name="visa" value="Yes" required>Yes</label>
      <label><input type="radio" name="visa" value="No" required>No</label></fieldset>
    <div id="follow"></div>
    <button type="submit">Submit Application</button>
  </form>
  <script>
    document.querySelectorAll('input[name=visa]').forEach(r => r.addEventListener('change', () => {
      document.getElementById('follow').innerHTML = r.value === 'Yes'
        ? '<label for="vt">Which visa type will you need? *</label><input id="vt" name="vt" required>' : '';
    }));
  </script>""")
CASCADE_URL = "https://boards.greenhouse.io/acme/jobs/77"


async def test_cascading_fields_revealed_by_an_answer_are_filled_in_a_rescan(web, tmp_path):
    page, site = web
    site.add(CASCADE_URL, CASCADE_FORM)
    await page.goto(CASCADE_URL)
    filler = HostedFormFiller(jitter=(0, 0))
    filler.settle_ms = 20
    owner = {"Will you require visa sponsorship?": "Yes", "Which visa type will you need?": "H-1B"}
    outcome = await filler.fill(page, gh_detail(), facts(tmp_path), hitl_answers=owner)
    assert outcome.question is None and outcome.passes >= 2
    assert [a["question"] for a in outcome.filled] == ["Will you require visa sponsorship?",
                                                       "Which visa type will you need?"]
    assert await page.evaluate("document.getElementById('vt').value") == "H-1B"
    # without an answer for the revealed question the owner is asked for exactly that question
    await page.goto(CASCADE_URL)
    asked = await filler.fill(page, gh_detail(), facts(tmp_path),
                              hitl_answers={"Will you require visa sponsorship?": "Yes"})
    assert asked.question is not None and asked.question.prompt == "Which visa type will you need?"


async def test_readback_aborts_when_a_required_value_silently_reverts(web, tmp_path):
    page, site = web
    revert = ("<script>document.getElementById('last_name').addEventListener('input', e => "
              "setTimeout(() => { e.target.value = ''; }, 5));</script>")
    site.add(GH_JOB, gh_form(extra=revert))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=3)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.WAITING_FOR_USER and result.reason == "form_readback_failed"
    assert "Last Name" in result.question.prompt and not result.clicked_apply
    assert not any("confirmation" in hit for hit in site.hits)


async def test_readback_aborts_when_the_resume_never_attaches(web, tmp_path):
    page, site = web
    drop = ("<script>document.getElementById('resume').addEventListener('change', e => "
            "{ e.target.value = ''; });</script>")
    site.add(GH_JOB, gh_form(extra=drop))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=3)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.state is S.WAITING_FOR_USER and result.reason == "resume_not_attached"


async def test_human_pulse_pauses_are_bounded_and_off_by_switch():
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    pulse = HumanPulse(enabled=True, sleep=record)
    await pulse.between_fields()
    await pulse.before_submit()
    assert 0.18 <= sleeps[0] <= 0.55 and 1.2 <= sleeps[1] <= 2.5
    assert 40 <= (pulse.keystroke_delay("Bengaluru") or 0) <= 120 and pulse.keystroke_delay("x" * 41) is None
    off = HumanPulse.from_jitter((0, 0))
    await off.before_submit()
    assert len(sleeps) == 2 and off.keystroke_delay("abc") is None


# --- Ashby -----------------------------------------------------------------------------------------------
ASHBY_ID = "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
ASHBY_JOB = f"https://jobs.ashbyhq.com/acme/{ASHBY_ID}"
ASHBY_FORM = html(f"""
  <h1>Backend Engineer</h1>
  <form action="/acme/{ASHBY_ID}/application/submitted" method="get">
    <label for="n">Name *</label><input id="n" name="name" required>
    <label for="e">Email *</label><input id="e" name="email" type="email" required>
    <label for="r">Resume *</label><input id="r" name="resume" type="file" required>
    <label for="q">How many years of experience do you have with Python? *</label><input id="q" name="q" required>
    <button type="submit">Submit Application</button>
  </form>""")


def ashby_adapter(tmp_path) -> AshbyAdapter:
    adapter = AshbyAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
    adapter.remember(FeedJob(external_job_id=ASHBY_ID, url=ASHBY_JOB, title="Backend Engineer", company="Acme",
                             apply_url=None, description="Python FastAPI PostgreSQL backend"))
    return adapter


async def test_ashby_dry_run_fills_and_stops_before_submit(web, tmp_path):
    page, site = web
    site.add(ASHBY_JOB + "/application", ASHBY_FORM)
    adapter = ashby_adapter(tmp_path)
    detail = await adapter.inspect_job(page, JobListing(platform="ashby", external_job_id=ASHBY_ID, url=ASHBY_JOB))
    assert detail.apply_mode == "direct" and detail.ats == "ashby"
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
    assert result.state is S.SCORED and result.reason == "dry_run_stopped_before_submit" and not result.clicked_apply
    assert not any("submitted" in hit for hit in site.hits)


async def test_ashby_live_apply_verifies_the_confirmation(web, tmp_path):
    page, site = web
    site.add(ASHBY_JOB + "/application", ASHBY_FORM)
    site.add(ASHBY_JOB + "/application/submitted",
             html("<h2>Your application was successfully submitted.</h2>"))
    adapter = ashby_adapter(tmp_path)
    detail = await adapter.inspect_job(page, JobListing(platform="ashby", external_job_id=ASHBY_ID, url=ASHBY_JOB))
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.receipt["ats"] == "ashby"
    assert "name=Test+Candidate" in site.hits[-1] and "q=3" in site.hits[-1]


# --- Naukri: semantic cache v2 metadata + rejection quarantine -----------------------------------------
@dataclass
class Resolved:
    answer: str | None
    source: str = "semantic_cache"
    reason: str = "cache_llm"
    cache_entry_id: str | None = "entry-42"


class FakeCache:
    def __init__(self) -> None:
        self.quarantined: list[str] = []

    async def record_form_validation_error(self, entry_id: str) -> None:
        self.quarantined.append(entry_id)


class FakeAnswerer:
    def __init__(self) -> None:
        self.cache = FakeCache()
        self.contexts: list[dict] = []

    async def resolve(self, question, options, facts, context=None):
        self.contexts.append(dict(context or {}))
        return Resolved("Yes")


def one_question_drawer(*, accept: bool) -> str:
    advance = ("d.remove(); document.body.insertAdjacentHTML('beforeend', "
               "'<div class=\"apply-message\">You have successfully applied to Backend Engineer</div>');"
               if accept else "render();")  # rejected: the same question is asked again
    return """<script>
window.answers = [];
function render() {
  const d = document.querySelector('.chatbot_DrawerContentWrapper');
  d.innerHTML = `<div class="chatbot_MessageContainer"><div class="botItem"><div class="botMsg">Are you comfortable with on-call rotations?</div></div></div>
    <div class="controls"><input class="ssrc__radio" type="radio" id="r1" value="Yes"><label class="ssrc__label" for="r1">Yes</label>
    <input class="ssrc__radio" type="radio" id="r2" value="No"><label class="ssrc__label" for="r2">No</label></div><div class="send">Save</div>`;
  d.querySelector('.send').onclick = () => { window.answers.push('saved'); setTimeout(() => { ADVANCE }, 50); };
}
document.querySelector('#job_header button').onclick = () => {
  document.body.insertAdjacentHTML('beforeend', '<div class="chatbot_DrawerContentWrapper"></div>');
  setTimeout(render, 50);
};
</script>""".replace("ADVANCE", advance)


async def test_naukri_passes_full_cache_metadata_and_records_the_entry(web, tmp_path):
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=one_question_drawer(accept=True)))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    answerer = FakeAnswerer()
    adapter.answerer = answerer
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.APPLIED and result.receipt["resume_variant_used"] == "portal_profile"
    context = answerer.contexts[0]
    assert context["platform"] == "naukri" and context["field_kind"] == "choice" and context["company"] == "Acme"
    assert "role_country" in context
    assert result.answers[0]["cache_entry_id"] == "entry-42" and answerer.cache.quarantined == []


async def test_naukri_rejected_cached_answer_is_quarantined(web, tmp_path):
    page, site = web
    site.add(NAUKRI_JOB, naukri_page("<button>Apply</button>", script=one_question_drawer(accept=False)))
    adapter = NaukriAdapter(settle_ms=10, refresh_wait_ms=10, jitter=(0, 0), receipts_dir=tmp_path / "naukri")
    answerer = FakeAnswerer()
    adapter.answerer = answerer
    detail = await adapter.inspect_job(page, naukri_listing())
    result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=False)
    assert result.state is S.SUBMISSION_UNKNOWN and result.reason == "questionnaire_stalled"
    assert answerer.cache.quarantined == ["entry-42"]
