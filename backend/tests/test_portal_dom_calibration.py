"""Live-calibrated DOM regression tests (2026-11-26 dry-run `--debug-selectors` sessions).

Every page below is a compact, synthetic reconstruction of the structure captured live in
`dom_probe.json` + `page.png` (no real data, no network: all requests are intercepted).
One class per portal: login/challenge detection, discovery/card parsing, form extraction,
dry-run stop-before-submit and limit detection where the portal has one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.adapters.base import AuthStatus, JobListing
from backend.app.browser_v2.adapters.challenge import (
    CHALLENGE_HELPERS_JS,
    CHALLENGE_SELECTOR,
)
from backend.app.browser_v2.adapters.feeds import MemoTransport
from backend.app.browser_v2.adapters.greenhouse import (
    EMBED_FORM,
    GreenhouseAdapter,
    hosted_apply_url,
)
from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
from backend.app.browser_v2.adapters.internshala import InternshalaAdapter
from backend.app.browser_v2.adapters.lever import LeverAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
from backend.app.browser_v2.adapters.work_at_a_startup import WorkAtAStartupAdapter
from backend.app.browser_v2.diagnostics import NAUKRI_SELECTORS
from backend.app.browser_v2.service import job_id_from_url
from backend.app.browser_v2.state import ApplicationState as S
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    facts,
    html,
    web_fixture,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

FAST: dict[str, Any] = {"settle_ms": 10, "refresh_wait_ms": 10, "jitter": (0, 0)}
CHALLENGE_PROBE = "() => {" + CHALLENGE_HELPERS_JS + """
  const body = (document.body && document.body.innerText) || "";
  return {nodes: challengeNodes(), title: challengeTitle(), text: challengeText(body)};
}"""

# --- live-shaped snapshots -----------------------------------------------------------------------
# naukri.com/nlogin/login: plain login + INVISIBLE reCAPTCHA (div.g-recaptcha, data-size=invisible, h=0).
NAUKRI_LOGIN = html("""
  <nav><button class="nI-gNb-sb__expand">Search jobs here</button><a href="/nlogin/login">Login</a></nav>
  <form name="login-form"><input id="usernameField" placeholder="Enter Email ID / Username">
    <input id="passwordField" type="password" placeholder="Enter Password">
    <button class="blue-btn">Login</button><button class="otpButton">Use OTP to Login</button>
    <div class="g-recaptcha" data-sitekey="TEST_FAKE_TOKEN_ONLY" data-size="invisible" style="height:0"></div>
  </form>""", "Jobseeker's Login: Search the Best Jobs available in India & Abroad - Naukri.com")
# instahyre.com: Cloudflare managed challenge (blank body, title only).
CF_INTERSTITIAL = html("<div id='cf'></div>", "Just a moment...")
INSTAHYRE_LOGIN = html("""
  <a href="/login/">Log in</a><a href="/candidates/register/">Sign up</a>
  <a href="/login/google-oauth2/?next=/login/">Sign in with Google</a>
  <form><input name="email" id="email"><input type="password" name="password" id="password">
  <button>Log in</button></form>""", "Login - Instahyre")
# wellfound.com/jobs while logged out: public listings with Apply buttons + nav "Log in" -> /login.
WELLFOUND_PUBLIC = html("""
  <header><a href="/login">Log in</a><a href="/jobs/signup?after_sign_in=%2Fjobs">Create profile</a></header>
  <h1>OVER 130K REMOTE &amp; LOCAL STARTUP JOBS</h1><input name="email" placeholder="Your Email">
  <div><a href="/jobs/3456789-backend-engineer">Backend Engineer</a><button>Save</button><button>Apply</button></div>
  """, "Find Startup Jobs Near You and Remote Jobs | Wellfound")
# workatastartup.com homepage (logged out) -> account.ycombinator.com magic link; /application -> YC account.
WAAS_HOME = html("""
  <a href="https://account.ycombinator.com/magic?continue=https%3A%2F%2Fwww.workatastartup.com%2F">Log in</a>
  <a href="https://account.ycombinator.com/authenticate?continue=https%3A%2F%2Fwww.workatastartup.com%2Fapplication">
  Sign up</a>""", "Startup Jobs at YC Companies | Y Combinator's Work at a Startup")
YC_ACCOUNT = html("""<h1>Log in or sign up to access Work at a Startup</h1>
  <input type="text" name="username" id="ycid-input"><button>Continue</button><button>Continue with Google</button>""",
                  "Account | Y Combinator")
# internshala.com/student/dashboard while logged out: the URL stays, a login modal is rendered.
INTERNSHALA_DASH_LOGGED_OUT = html("""
  <div class="modal"><form><input type="email" name="email" id="email" placeholder="john@example.com">
  <input type="password" name="password" id="password"><button>Login</button></form></div>""",
                                   "Search Internships, Jobs, & Courses | Internshala")
# job-boards.greenhouse.io/embed/job_app (stripe board, custom career site) - live field inventory.
GH_EMBED_FORM = html("""
  <form id="application-form" class="application--form">
   <label for="first_name">First Name *</label><input id="first_name" name="first_name" required aria-required="true">
   <label for="last_name">Last Name *</label><input id="last_name" name="last_name" required aria-required="true">
   <label for="email">Email *</label><input id="email" name="email" type="text" required aria-required="true">
   <label for="phone">Phone</label><input id="phone" name="phone" type="tel">
   <label for="resume">Resume/CV *</label><input id="resume" name="resume" type="file" required>
   <label for="cover_letter">Cover Letter</label><input id="cover_letter" name="cover_letter" type="file">
   <label for="question_71091314">Who is your current or previous employer?</label>
   <input id="question_71091314" name="question_71091314">
   <button type="submit" id="submit_app">Submit application</button>
  </form>
  <script>window.SUBMITS = 0; document.getElementById('application-form').onsubmit =
    (e) => { e.preventDefault(); window.SUBMITS += 1; };</script>""", "Job Application for Software Engineer")


async def serve(page: Any, site: Any, url: str, body: str) -> None:
    site.add(url, body)
    await page.goto(url)


# --- shared challenge detector ---------------------------------------------------------------------
class TestSharedChallengeDetection:
    async def test_invisible_recaptcha_is_not_a_challenge(self, web):
        page, site = web
        await serve(page, site, "https://www.naukri.com/nlogin/login", NAUKRI_LOGIN)
        assert await page.evaluate(CHALLENGE_PROBE) == {"nodes": False, "title": False, "text": False}

    async def test_rendered_recaptcha_widget_is_a_challenge(self, web):
        page, site = web
        await serve(page, site, "https://example.com/c", html(
            '<div class="g-recaptcha" data-sitekey="TEST_FAKE_TOKEN_ONLY" style="width:304px;height:78px"></div>'))
        assert (await page.evaluate(CHALLENGE_PROBE))["nodes"] is True

    async def test_invisible_recaptcha_anchor_iframe_is_ignored(self, web):
        page, site = web
        await serve(page, site, "https://example.com/i", html(
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible" '
            'style="width:256px;height:60px"></iframe>'))
        assert (await page.evaluate(CHALLENGE_PROBE))["nodes"] is False

    async def test_cloudflare_title_interstitial_is_a_challenge(self, web):
        page, site = web
        await serve(page, site, "https://www.instahyre.com/login/google-oauth2", CF_INTERSTITIAL)
        assert (await page.evaluate(CHALLENGE_PROBE))["title"] is True

    async def test_recaptcha_legal_notice_is_not_challenge_copy(self, web):
        page, site = web
        await serve(page, site, "https://example.com/n", html(
            "<p>This site is protected by reCAPTCHA and the Google Privacy Policy applies.</p>"))
        assert (await page.evaluate(CHALLENGE_PROBE))["text"] is False

    def test_diagnostics_use_the_same_selector(self):
        assert NAUKRI_SELECTORS["captcha"] == CHALLENGE_SELECTOR
        assert ':not([data-size="invisible"])' in CHALLENGE_SELECTOR


# --- 1. naukri -----------------------------------------------------------------------------------------
class TestNaukri:
    async def test_login_page_is_login_not_challenge(self, web):
        page, site = web
        site.add("https://www.naukri.com/mnjuser/homepage", html("<script>location.href='/nlogin/login'</script>"))
        site.add("https://www.naukri.com/nlogin/login", NAUKRI_LOGIN)
        session = await NaukriAdapter(settle_ms=10, refresh_wait_ms=10).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"
        assert session.details["first"] == session.details["second"] == "login"

    async def test_real_captcha_on_login_still_fails_closed(self, web):
        page, site = web
        site.add("https://www.naukri.com/mnjuser/homepage", html(
            '<iframe src="https://www.google.com/recaptcha/api2/bframe" style="width:400px;height:580px"></iframe>'))
        session = await NaukriAdapter(settle_ms=10, refresh_wait_ms=10).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "challenge"


# --- 2. instahyre --------------------------------------------------------------------------------------
class TestInstahyre:
    async def test_cloudflare_interstitial_is_challenge_not_login(self, web, tmp_path):
        page, site = web
        site.add("https://www.instahyre.com/candidate/opportunities", CF_INTERSTITIAL)
        session = await InstahyreAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "challenge"

    async def test_login_redirect_is_login(self, web, tmp_path):
        page, site = web
        site.add("https://www.instahyre.com/candidate/opportunities",
                 html("<script>location.href='/login/?next=/candidate/opportunities/'</script>"))
        site.add("https://www.instahyre.com/login", INSTAHYRE_LOGIN)
        session = await InstahyreAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"


# --- 3. internshala ------------------------------------------------------------------------------------
class TestInternshala:
    async def test_dashboard_url_with_login_modal_is_login(self, web, tmp_path):
        page, site = web
        site.add("https://internshala.com/student/dashboard", INTERNSHALA_DASH_LOGGED_OUT)
        session = await InternshalaAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"


# --- 4. wellfound --------------------------------------------------------------------------------------
class TestWellfound:
    async def test_public_jobs_page_logged_out_is_login_not_unknown(self, web, tmp_path):
        page, site = web
        site.add("https://wellfound.com/jobs", WELLFOUND_PUBLIC)
        session = await WellfoundAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"

    async def test_logged_in_nav_wins_over_public_markers(self, web, tmp_path):
        page, site = web
        site.add("https://wellfound.com/jobs", html('<a href="/jobs/applications">Applications</a>'
                                                    '<a href="/logout">Log out</a>'))
        assert (await WellfoundAdapter(receipts_root=tmp_path, **FAST).check_session(page)).status is AuthStatus.OK


# --- 5. work_at_a_startup ------------------------------------------------------------------------------
class TestWorkAtAStartup:
    async def test_yc_account_redirect_is_login(self, web, tmp_path):
        page, site = web
        site.add("https://www.workatastartup.com/application",
                 html("<script>location.href='https://account.ycombinator.com/'</script>"))
        site.add("https://account.ycombinator.com", YC_ACCOUNT)
        session = await WorkAtAStartupAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"

    async def test_public_homepage_magic_link_counts_as_login_form(self, web, tmp_path):
        page, site = web
        site.add("https://www.workatastartup.com/application", WAAS_HOME)
        session = await WorkAtAStartupAdapter(receipts_root=tmp_path, **FAST).check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"


# --- 6. greenhouse -------------------------------------------------------------------------------------
def gh_board(count: int, *, absolute: str = "https://stripe.com/jobs/search?gh_jid={id}") -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"jobs": [{"id": 1000 + i, "title": "Backend Engineer" if i == count - 1 else f"Analyst {i}",
                      "absolute_url": absolute.format(id=1000 + i), "location": {"name": "Remote"},
                      "first_published": (now - timedelta(days=1 if i == count - 1 else 90)).isoformat(),
                      "updated_at": now.isoformat(), "content": "&lt;p&gt;Python&lt;/p&gt;"} for i in range(count)]}


class Counter:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.hits: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.hits.append(request.url.path)
        for suffix, payload in self.routes.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})


class TestGreenhouse:
    def test_custom_career_site_routes_to_embed_form(self):
        assert hosted_apply_url("stripe", "8172510", "https://stripe.com/jobs/search?gh_jid=8172510") == \
            EMBED_FORM.format(token="stripe", job_id="8172510")
        hosted = "https://job-boards.greenhouse.io/gitlab/jobs/8940982002"
        assert hosted_apply_url("gitlab", "8940982002", hosted) == hosted

    def test_job_id_from_custom_site_and_embed_urls(self):
        assert job_id_from_url("greenhouse", "https://stripe.com/jobs/search?gh_jid=8172510") == "8172510"
        assert job_id_from_url("greenhouse",
                               "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=8172510") == "8172510"
        assert job_id_from_url("greenhouse", "https://evil.example/?gh_jid=12ab") is None

    async def test_big_board_reads_every_page_from_one_download_and_never_starves_others(self):
        counter = Counter({"/boards/stripe/jobs": gh_board(772), "/boards/gitlab/jobs": gh_board(3)})
        client = httpx.AsyncClient(transport=MemoTransport(httpx.MockTransport(counter)))
        adapter = GreenhouseAdapter(boards={"stripe": None, "gitlab": None}, http_client=client)
        jobs = await adapter.fetch("engineer", 50)
        assert len(jobs) == 775  # stripe 772 (8 pages) + gitlab 3: the first board no longer starves the second
        assert counter.hits.count("/v1/boards/stripe/jobs") == 1  # pages sliced from one memoized download
        found = await adapter.discover_jobs(None, query="backend engineer", limit=10, job_age_days=7)
        assert {j.company for j in found} == {"stripe", "gitlab"} or len(found) == 2
        stripe_job = adapter.jobs[found[0].external_job_id]
        assert (stripe_job.apply_url or "").startswith("https://job-boards.greenhouse.io/")
        await client.aclose()

    async def test_embed_form_extraction_and_dry_run_stops_before_submit(self, web, tmp_path):
        page, site = web
        url = EMBED_FORM.format(token="stripe", job_id="8172510")
        site.add(url, GH_EMBED_FORM)
        adapter = GreenhouseAdapter(boards={"stripe": "Stripe"}, receipts_root=tmp_path, settle_ms=10,
                                    confirm_timeout_s=1)
        from backend.app.browser_v2.adapters.feeds import FeedJob

        job = FeedJob(external_job_id="8172510", url="https://stripe.com/jobs/search?gh_jid=8172510",
                      title="Software Engineer", company="Stripe", apply_url=url, description="Python",
                      posted_at=datetime.now(UTC))
        adapter.remember(job)
        detail = await adapter.inspect_job(page, adapter.listing(job))
        assert detail.apply_mode == "direct" and detail.ats == "greenhouse" and detail.challenge is None
        form = json.dumps(await adapter.extract_form(page))
        for name in ("first_name", "last_name", "email", "phone", "resume", "question_71091314"):
            assert name in form
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert result.state is not S.APPLIED and result.reason in {"dry_run_stopped_before_submit",
                                                                   "question_requires_owner"}
        assert await page.evaluate("window.SUBMITS") == 0


# --- 7. lever ------------------------------------------------------------------------------------------
def lever_posting(board: str, index: int, *, title: str, days: int) -> dict[str, Any]:
    pid = f"{index:08x}-aaaa-bbbb-cccc-1234567890ab"
    created = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)
    return {"id": pid, "text": title, "hostedUrl": f"https://jobs.lever.co/{board}/{pid}",
            "applyUrl": f"https://jobs.lever.co/{board}/{pid}/apply", "createdAt": created,
            "categories": {"location": "Remote", "commitment": "Full-time"}, "descriptionPlain": "Python"}


class TestLever:
    async def test_all_postings_paged_from_one_download_and_second_board_read(self):
        palantir = [lever_posting("palantir", i, title=f"Deployment Strategist {i}", days=40) for i in range(305)]
        spotify = [lever_posting("spotify", 900 + i, title="Senior Backend Engineer", days=1) for i in range(2)]
        counter = Counter({"/postings/palantir": palantir, "/postings/spotify": spotify})
        client = httpx.AsyncClient(transport=MemoTransport(httpx.MockTransport(counter)))
        adapter = LeverAdapter(boards={"palantir": None, "spotify": None}, http_client=client)
        assert len(await adapter.fetch("engineer", 50)) == 307
        assert counter.hits.count("/v0/postings/palantir") == 1
        found = await adapter.discover_jobs(None, query="backend engineer", limit=5, job_age_days=7)
        assert [j.company for j in found] == ["spotify", "spotify"] and all((j.posted_age_days or 0) <= 1 for j in found)
        await client.aclose()

    def test_lever_job_ids(self):
        pid = "2a55d6c9-c564-443a-be3e-a3851db5a93b"
        assert job_id_from_url("lever", f"https://jobs.lever.co/spotify/{pid}/apply") == pid


def test_listing_type_is_shared():
    assert JobListing(platform="lever", external_job_id="x", url="https://jobs.lever.co/a/b").platform == "lever"


# --- 7b. lever labels ----------------------------------------------------------------------------------
def test_lever_required_marker_is_stripped_from_labels():
    from backend.app.browser_v2.adapters.common import clean_label

    assert clean_label("Current company ✱") == "Current company"  # live jobs.lever.co marker
    assert clean_label("First Name *") == "First Name" and clean_label("Email (required)") == "Email"


# --- 8. himalayas --------------------------------------------------------------------------------------
HIM_PAGE = "https://himalayas.app/companies/acme/jobs/backend-engineer"
HIM_API_LINK = HIM_PAGE + "?utm_source=api"


def himalayas_job(link: str = HIM_API_LINK):
    from backend.app.browser_v2.adapters.feeds import FeedJob

    return FeedJob(external_job_id="acme-backend", url=HIM_PAGE, title="Backend Engineer", company="Acme",
                   apply_url=link, description="Python", posted_at=datetime.now(UTC))


class TestHimalayas:
    async def test_api_link_back_to_himalayas_resolves_employer_ats_from_page(self, web, tmp_path):
        from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter

        page, site = web
        site.add(HIM_PAGE, html('<a href="https://job-boards.greenhouse.io/acme/jobs/123">Apply now</a>'))
        adapter = HimalayasAdapter(receipts_root=tmp_path, settle_ms=10)
        job = himalayas_job()
        assert await adapter.resolve_apply_url(page, job) == "https://job-boards.greenhouse.io/acme/jobs/123"
        direct = himalayas_job("https://jobs.lever.co/acme/2a55d6c9-c564-443a-be3e-a3851db5a93b")
        assert await adapter.resolve_apply_url(None, direct) == direct.apply_url  # no navigation needed

    async def test_cloudflare_on_job_page_fails_closed_and_isolates_portal(self, web, tmp_path):
        from backend.app.browser_v2.adapters.feeds import PortalWallActive
        from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter

        page, site = web
        site.add(HIM_PAGE, CF_INTERSTITIAL)
        adapter = HimalayasAdapter(receipts_root=tmp_path, settle_ms=10)
        job = himalayas_job()
        adapter.remember(job)
        detail = await adapter.inspect_job(page, adapter.listing(job))
        assert detail.challenge == "challenge" and detail.apply_mode == "direct"
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert result.state is S.WAITING_FOR_USER and result.question is not None and result.question.kind == "CAPTCHA"  # not FILTERED_OUT
        session = await adapter.check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "challenge"
        with pytest.raises(PortalWallActive):
            await adapter.inspect_job(page, adapter.listing(job))


# --- 9. we_work_remotely -------------------------------------------------------------------------------
WWR_JOB = "https://weworkremotely.com/remote-jobs/acme-backend-engineer"


class TestWeWorkRemotely:
    async def test_register_wall_is_login_hitl_not_apply_control_none(self, web, tmp_path):
        from backend.app.browser_v2.adapters.feeds import FeedJob
        from backend.app.browser_v2.adapters.we_work_remotely import (
            WeWorkRemotelyAdapter,
        )

        page, site = web
        register = "/job-seekers/account/register?alert=Create+an+account+to+view+full+job+details."
        site.add(WWR_JOB, html(f'<a id="job-cta-alt" href="{register}">Apply now</a>'
                               '<a id="listing-details-job-copilot-cta-header" href="/career-services/job-copilot">'
                               'AI Auto-Apply</a>'))
        adapter = WeWorkRemotelyAdapter(receipts_root=tmp_path, settle_ms=10)
        job = FeedJob(external_job_id="acme-backend-engineer", url=WWR_JOB, title="Backend Engineer",
                      company="Acme", apply_url=None, description="Python", posted_at=datetime.now(UTC))
        adapter.remember(job)
        detail = await adapter.inspect_job(page, adapter.listing(job))
        assert detail.challenge == "login"
        result = await adapter.apply_job(page, detail, facts(tmp_path), dry_run=True)
        assert result.question is not None
        assert (result.state, result.reason, result.question.kind) == (S.WAITING_FOR_USER, "portal_login_required",
                                                                     "AUTH")
        session = await adapter.check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "login"

    async def test_external_apply_link_still_resolves(self, web, tmp_path):
        from backend.app.browser_v2.adapters.feeds import FeedJob
        from backend.app.browser_v2.adapters.we_work_remotely import (
            WeWorkRemotelyAdapter,
        )

        page, site = web
        site.add(WWR_JOB, html('<a id="job-cta-alt" href="https://jobs.lever.co/acme/'
                               '2a55d6c9-c564-443a-be3e-a3851db5a93b">Apply now</a>'))
        adapter = WeWorkRemotelyAdapter(receipts_root=tmp_path, settle_ms=10)
        job = FeedJob(external_job_id="acme-backend-engineer", url=WWR_JOB, title="Backend Engineer",
                      company="Acme", apply_url=None, description="Python", posted_at=datetime.now(UTC))
        assert (await adapter.resolve_apply_url(page, job) or "").startswith("https://jobs.lever.co/acme/")


# --- 10. hiringcafe ------------------------------------------------------------------------------------
class TestHiringCafe:
    async def test_cloudflare_search_page_yields_no_junk_cards(self, web, tmp_path):
        from backend.app.browser_v2.adapters.hiringcafe import HiringCafeAdapter

        page, site = web
        adapter = HiringCafeAdapter(receipts_root=tmp_path, **FAST)
        # Live 2026-11-26: hiring.cafe -> hiringcafe.com "Just a moment..." with on-host links.
        challenge = html('<h1>hiringcafe.com</h1><a href="/viewjob/abc123xyz">hiringcafe.com</a>', "Just a moment...")
        site.add("https://hiring.cafe", challenge)
        assert await adapter.discover_jobs(page, query="software engineer", limit=5, job_age_days=7) == []
        assert adapter.last_discovery_blocked == "challenge"
        session = await adapter.check_session(page)
        assert session.status is AuthStatus.AUTH_REQUIRED and session.reason == "challenge"

    async def test_clean_search_page_parses_cards(self, web, tmp_path):
        from backend.app.browser_v2.adapters.hiringcafe import HiringCafeAdapter

        page, site = web
        adapter = HiringCafeAdapter(receipts_root=tmp_path, **FAST)
        site.add("https://hiring.cafe", html('<article class="job-card"><a href="/viewjob/abc123xyz"><h3>Backend '
                                             'Engineer</h3></a><span class="company">Acme</span>'
                                             '<span>Posted 2 days ago</span></article>', "HiringCafe"))
        jobs = await adapter.discover_jobs(page, query="backend engineer", limit=5, job_age_days=7)
        assert [(j.external_job_id, j.title, j.company, j.posted_age_days) for j in jobs] == [
            ("abc123xyz", "Backend Engineer", "Acme", 2)]
        assert adapter.last_discovery_blocked is None


# --- public search cards (live 2026-11-26 structures) --------------------------------------------------
INTERNSHALA_CARDS = html("""
  <div class="container-fluid individual_internship logged_out_jd_summary">
    <div class="internship_meta experience_meta"><div class="internship-heading-container">
      <div class="company generic_company"><div class="generic_container"><h2 class="job-internship-name">
        <a class="job-title-href" href="/job/detail/python-development-job-at-uv-farms1794375277">Python Development</a>
      </h2></div><p class="company-name">UV Farms Private Limited <span>Active</span></p></div></div>
      <div class="status-success">2 weeks ago</div></div></div>
  <div class="container-fluid individual_internship logged_out_jd_summary">
    <div class="internship_meta experience_meta"><div class="internship-heading-container">
      <div class="company generic_company"><div class="generic_container"><h2 class="job-internship-name">
        <a class="job-title-href" href="/job/detail/python-development-job-at-pledge1795685126">Python Development</a>
      </h2></div><p class="company-name">Pledge India Foundation Active</p></div></div>
      <div class="status-success">Just now</div></div></div>""", "Jobs | Internshala")
WELLFOUND_CARDS = html("""
  <div class="mb-6 w-full rounded border"><a href="/company/acme-ai">Acme AI</a>
    <div class="mb-4 w-full px-4"><div class="w-full pb-1"><div class="mb-1 flex items-start">
      <a class="mr-2 text-sm font-semibold" href="/jobs/5127264-python-developer">Python Developer</a>
      <span>Full-time</span></div><span class="text-xs">5 days ago</span></div></div>
    <div class="mb-4 w-full px-4"><div class="w-full pb-1"><div class="mb-1 flex items-start">
      <a class="mr-2 text-sm font-semibold" href="/jobs/4881201-backend-engineer">Backend Engineer</a>
      <span>Full-time</span></div><span class="text-xs">30 days ago</span></div></div></div>
  <div class="mb-6 w-full rounded border"><a href="/company/beta">Beta</a>
    <div class="mb-4 w-full px-4"><div class="mb-1 flex items-start">
      <a href="/jobs/4823723-python-developer">Python Developer</a></div><span>1 day ago</span></div></div>""",
                       "Remote Python Developer Jobs | Wellfound")


class TestPublicSearchCards:
    async def test_internshala_cards_carry_company_and_age(self, web, tmp_path):
        page, site = web
        site.add("https://internshala.com/jobs/keywords-python-developer", INTERNSHALA_CARDS)
        jobs = await InternshalaAdapter(receipts_root=tmp_path, **FAST).discover_jobs(
            page, query="python developer", limit=5)
        assert [(j.external_job_id, j.company, j.posted_age_days) for j in jobs] == [
            ("1794375277", "UV Farms Private Limited", 14), ("1795685126", "Pledge India Foundation", 0)]

    async def test_wellfound_cards_take_age_from_row_and_company_from_block(self, web, tmp_path):
        page, site = web
        site.add("https://wellfound.com/role/r/python-developer", WELLFOUND_CARDS)
        jobs = await WellfoundAdapter(receipts_root=tmp_path, **FAST).discover_jobs(
            page, query="python developer", limit=5)
        assert [(j.external_job_id, j.company, j.posted_age_days) for j in jobs] == [
            ("5127264", "Acme AI", 5), ("4881201", "Acme AI", 30), ("4823723", "Beta", 1)]
