from pathlib import Path

from backend.app.browser_v2.adapters.base import (
    AuthStatus,
    JobDetail,
    JobListing,
    PortalAdapter,
)
from backend.app.browser_v2.adapters.naukri import (
    NaukriAdapter,
    classify_auth,
    external_job_id,
    search_url,
)
from backend.app.browser_v2.answers import CandidateFacts, resolve_answer
from backend.app.browser_v2.rules import parse_applicants
from backend.app.browser_v2.state import ApplicationState

LOGGED_IN = {"url": "https://www.naukri.com/mnjuser/homepage", "loggedIn": True}
LOGIN_PAGE = {"url": "https://www.naukri.com/nlogin/login?URL=/mnjuser/homepage", "loginForm": True}
OTP_PAGE = {"url": "https://www.naukri.com/nlogin/login", "otp": True}


class FakeContext:
    def __init__(self, cookies=("nauk_rt",)):
        self._cookies = [{"name": n} for n in cookies]
        self.pages = []

    async def cookies(self, _origin):
        return self._cookies


class FakePage:
    def __init__(self):
        self.calls = []
        self.context = FakeContext()

    async def goto(self, url, **_):
        self.calls.append(("goto", url))

    async def reload(self, **_):
        self.calls.append(("reload",))

    async def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))


class ScriptedNaukri(NaukriAdapter):
    def __init__(self, probes):
        super().__init__(refresh_wait_ms=1, settle_ms=0, receipts_dir=Path("/nonexistent"))
        self.probes = list(probes)

    async def _probe(self, page):
        return self.probes.pop(0)


async def test_session_ok_without_refresh():
    page = FakePage()
    result = await ScriptedNaukri([LOGGED_IN]).check_session(page)
    assert result.status is AuthStatus.OK and not result.refreshed
    assert ("reload",) not in page.calls


async def test_expired_access_token_refreshes_once_then_ok():
    page = FakePage()
    result = await ScriptedNaukri([LOGIN_PAGE, LOGGED_IN]).check_session(page)
    assert result.status is AuthStatus.OK and result.refreshed
    assert page.calls.count(("reload",)) == 1
    assert result.details["has_refresh_cookie"] is True


async def test_still_login_after_refresh_is_auth_required():
    page = FakePage()
    result = await ScriptedNaukri([LOGIN_PAGE, LOGIN_PAGE]).check_session(page)
    assert result.status is AuthStatus.AUTH_REQUIRED and result.reason == "login"
    assert page.calls.count(("reload",)) == 1


async def test_otp_after_refresh_is_auth_required():
    result = await ScriptedNaukri([LOGIN_PAGE, OTP_PAGE]).check_session(FakePage())
    assert result.status is AuthStatus.AUTH_REQUIRED and result.reason == "otp"


async def test_unrecognized_page_is_unknown_not_auth_required():
    blank = {"url": "https://www.naukri.com/mnjuser/homepage"}
    result = await ScriptedNaukri([blank, blank]).check_session(FakePage())
    assert result.status is AuthStatus.UNKNOWN


def test_classify_auth_prefers_challenge():
    assert classify_auth({"url": "https://www.naukri.com/mnjuser/homepage", "loggedIn": True,
                          "challenge": True}) == "challenge"
    assert classify_auth(LOGGED_IN) == "ok"
    assert classify_auth(LOGIN_PAGE) == "login"


def test_job_url_helpers():
    url = "https://www.naukri.com/job-listings-python-developer-acme-bengaluru-1-to-3-years-261126012345"
    assert external_job_id(url) == "261126012345"
    assert external_job_id("https://www.naukri.com/python-jobs") is None
    assert search_url("python developer", job_age_days=7) == (
        "https://www.naukri.com/python-developer-jobs?k=python+developer&jobAge=7")


def test_naukri_adapter_satisfies_protocol():
    assert isinstance(NaukriAdapter(), PortalAdapter)


def detail(**overrides):
    listing = JobListing(platform="naukri", external_job_id="261126012345",
                         url="https://www.naukri.com/job-listings-x-261126012345", title="Dev", company="Acme")
    values = dict(listing=listing, applicants=parse_applicants("100+"), posted_age_days=1,
                  already_applied=False, apply_mode="direct")
    values.update(overrides)
    return JobDetail(**values)


async def test_apply_classifies_without_touching_page():
    adapter = NaukriAdapter()
    page = object()
    facts = CandidateFacts()
    assert (await adapter.apply_job(page, detail(apply_mode="external"), facts)).state is ApplicationState.FILTERED_OUT
    limit = await adapter.apply_job(page, detail(portal_limit="daily apply limit"), facts)
    assert limit.state is ApplicationState.QUOTA_HIT_PENDING
    captcha = await adapter.apply_job(page, detail(challenge="challenge"), facts)
    assert captcha.state is ApplicationState.WAITING_FOR_USER and captcha.question.kind == "CAPTCHA"
    applied = await adapter.apply_job(page, detail(already_applied=True), facts)
    assert applied.state is ApplicationState.APPLIED and not applied.clicked_apply


async def test_apply_refuses_never_replay_state():
    import pytest

    from backend.app.browser_v2.state import ReplayRefused

    with pytest.raises(ReplayRefused):
        await NaukriAdapter().apply_job(object(), detail(), CandidateFacts(),
                                        existing_state="SUBMISSION_UNKNOWN")


def test_deterministic_answers_and_hitl_fallback():
    facts = CandidateFacts.from_profile({
        "verified_experience_years": 2, "verified_skills": ["Python", {"name": "React"}],
        "preferences": {"notice_period_days": 30, "expected_ctc": "8 LPA", "current_location": "Bengaluru",
                        "skill_years": {"Python": 2}},
    })
    assert resolve_answer("What is your total experience in years?", (), facts) == "2"
    assert resolve_answer("How many years of experience do you have in Python?", (), facts) == "2"
    assert resolve_answer("How many years of experience do you have in Go?", (), facts) is None
    assert resolve_answer("Do you have experience with React?", ("Yes", "No"), facts) == "Yes"
    assert resolve_answer("Do you have experience with Kubernetes?", ("Yes", "No"), facts) == "No"
    assert resolve_answer("What is your notice period?",
                          ("15 Days or less", "1 Month", "2 Months", "3 Months"), facts) == "1 Month"
    assert resolve_answer("What is your expected CTC?", (), facts) == "8 LPA"
    assert resolve_answer("What is your current CTC?", (), facts) is None
    assert resolve_answer("Enter the OTP sent to your phone", (), facts) is None
    assert resolve_answer("Why do you want to join us?", (), facts) is None
