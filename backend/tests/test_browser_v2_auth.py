"""Phase 6A smart auto re-login on real headless Chromium with intercepted pages:
Keychain email+password (+ auto email OTP), trusted Google chip, hard refusal to type on
accounts.google.com, 30-minute cooldown, the Keychain vault and the set-portal-cred CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.browser_v2 import cli
from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
from backend.app.browser_v2.auth import (
    AutoLogin,
    GoogleTypingRefused,
    KeychainVault,
    LoginSpec,
    MemoryVault,
    safe_fill,
)
from backend.tests.phase6a_fixtures import chromium_fixture, html, web_fixture  # noqa: F401

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

LOGIN = "https://www.instahyre.com/login"
HOME = "https://www.instahyre.com/candidate/opportunities"
LOGGED_IN = html('<a href="/candidate/profile/">My profile</a><h1>Opportunities</h1>')
LOGIN_PAGE = html("""
  <form id="f"><input type="email" id="email"><input type="password" id="pw"><button id="go">Login</button></form>
  <div id="otp" style="display:none"><input name="otp" id="code"><button id="verify">Verify</button></div>
  <script>
    document.getElementById('go').onclick = (e) => {
      e.preventDefault();
      if (document.getElementById('email').value === 'owner@example.com' &&
          document.getElementById('pw').value === 'TEST_FAKE_TOKEN_ONLY') {
        if (window.NEED_OTP) { document.getElementById('f').style.display = 'none';
                               document.getElementById('otp').style.display = 'block'; }
        else location.href = '/candidate/opportunities';
      }
    };
    document.getElementById('verify').onclick = () => {
      if (document.getElementById('code').value === '482913') location.href = '/candidate/opportunities';
    };
  </script>""")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class FakeReader:
    def __init__(self, code="482913"):
        self.code = code
        self.calls = []

    async def poll_otp(self, portal, since, *, timeout_s=45.0):
        self.calls.append((portal, timeout_s))
        return self.code


def instahyre(tmp_path):
    return InstahyreAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0))


SPECS = {"instahyre": LoginSpec(LOGIN, google_sso=False), "wellfound": LoginSpec("https://wellfound.com/login",
                                                                                 password_login=False, google_sso=True)}
CREDS = MemoryVault({"instahyre": ("owner@example.com", "TEST_FAKE_TOKEN_ONLY")})


async def test_keychain_password_login_succeeds(web, tmp_path):
    page, site = web
    site.add(LOGIN, LOGIN_PAGE)
    site.add(HOME, LOGGED_IN)
    login = AutoLogin(CREDS, specs=SPECS, settle_ms=50, clock=Clock())
    result = await login.attempt("instahyre", page, instahyre(tmp_path))
    assert result.ok and result.method == "password" and result.reason == "logged_in"


async def test_password_login_with_auto_email_otp(web, tmp_path):
    page, site = web
    site.add(LOGIN, LOGIN_PAGE.replace("<script>", "<script>window.NEED_OTP = true;"))
    site.add(HOME, LOGGED_IN)
    reader = FakeReader()
    login = AutoLogin(CREDS, reader, specs=SPECS, settle_ms=50, clock=Clock(), otp_timeout_s=5)
    result = await login.attempt("instahyre", page, instahyre(tmp_path))
    assert result.ok and result.method == "password+email_otp" and reader.calls == [("instahyre", 5)]


async def test_missing_email_otp_or_reader_becomes_an_otp_hitl(web, tmp_path):
    page, site = web
    site.add(LOGIN, LOGIN_PAGE.replace("<script>", "<script>window.NEED_OTP = true;"))
    no_reader = await AutoLogin(CREDS, None, specs=SPECS, settle_ms=50, clock=Clock()).attempt(
        "instahyre", page, instahyre(tmp_path))
    assert not no_reader.ok and no_reader.hitl_kind == "OTP" and no_reader.reason == "otp_required_no_mail_reader"
    silent = await AutoLogin(CREDS, FakeReader(code=None), specs=SPECS, settle_ms=50, clock=Clock()).attempt(
        "instahyre", page, instahyre(tmp_path))
    assert not silent.ok and silent.hitl_kind == "OTP" and silent.reason == "email_otp_not_received"


async def test_cooldown_allows_one_attempt_per_portal_per_30_minutes(web, tmp_path):
    page, site = web
    site.add(LOGIN, html("<p>maintenance</p>"))
    clock = Clock()
    login = AutoLogin(CREDS, specs=SPECS, settle_ms=10, clock=clock)
    first = await login.attempt("instahyre", page, instahyre(tmp_path))
    hits = len(site.hits)
    second = await login.attempt("instahyre", page, instahyre(tmp_path))
    assert not first.ok and second.reason == "auto_login_cooldown" and len(site.hits) == hits  # no navigation
    clock.now += timedelta(minutes=31)
    third = await login.attempt("instahyre", page, instahyre(tmp_path))
    assert third.reason != "auto_login_cooldown"


GOOGLE_CHIP = html("""
  <ul><li><div data-identifier="candidate@example.com" role="link" tabindex="0"
      onclick="location.href='https://wellfound.com/jobs'">Test Candidate · candidate@example.com</div></li></ul>""")
GOOGLE_PASSWORD = html('<h1>Welcome</h1><input type="password" name="Passwd"><button>Next</button>')
WELLFOUND_LOGIN = html("""<button onclick="location.href='https://accounts.google.com/o/oauth2/v2/auth?client_id=x'">
  Continue with Google</button>""")


def wellfound(tmp_path):
    return WellfoundAdapter(receipts_root=tmp_path, settle_ms=10, refresh_wait_ms=10, jitter=(0, 0))


async def test_trusted_google_chip_click(web, tmp_path):
    page, site = web
    site.add("https://wellfound.com/login", WELLFOUND_LOGIN)
    site.add("https://accounts.google.com/o/oauth2/v2/auth", GOOGLE_CHIP)
    site.add("https://wellfound.com/jobs", html('<a href="/jobs/applications">Applications</a><h1>Jobs</h1>'))
    login = AutoLogin(MemoryVault(), specs=SPECS, settle_ms=50, clock=Clock(), owner_email="candidate@example.com")
    result = await login.attempt("wellfound", page, wellfound(tmp_path))
    assert result.ok and result.method == "google_chip", result


async def test_google_password_or_2fa_screen_aborts_without_typing(web, tmp_path):
    page, site = web
    site.add("https://wellfound.com/login", WELLFOUND_LOGIN)
    site.add("https://accounts.google.com/o/oauth2/v2/auth", GOOGLE_PASSWORD)
    login = AutoLogin(MemoryVault(), specs=SPECS, settle_ms=50, clock=Clock())
    result = await login.attempt("wellfound", page, wellfound(tmp_path))
    assert not result.ok and result.hitl_kind == "AUTH" and result.reason == "google_password_or_2fa_required"
    assert await page.evaluate("document.querySelector('input[type=password]').value") == ""
    with pytest.raises(GoogleTypingRefused):
        await safe_fill(page, "input[type=password]", "TEST_FAKE_TOKEN_ONLY")
    site.add("https://accounts.google.com/o/oauth2/v2/auth", html("<p>Choose an account</p>"
                                                                  '<div data-identifier="a@example.com">A</div>'
                                                                  '<div data-identifier="b@example.com">B</div>'))
    login.last_attempt.clear()
    ambiguous = await login.attempt("wellfound", page, wellfound(tmp_path))
    assert not ambiguous.ok and ambiguous.reason == "google_account_chip_ambiguous"


async def test_unsupported_portal_and_missing_credentials():
    login = AutoLogin(MemoryVault(), specs=SPECS, clock=Clock())
    assert (await login.attempt("greenhouse", object(), object())).reason == "auto_login_unsupported"
    only_password = AutoLogin(MemoryVault(), specs={"instahyre": LoginSpec(LOGIN)}, clock=Clock())
    assert (await only_password.attempt("instahyre", object(), object())).reason == "no_keychain_credentials"


# --- Keychain vault + CLI ---------------------------------------------------------------------------
class FakeKeyring:
    def __init__(self):
        self.items = {}

    def set_password(self, service, user, secret):
        self.items[(service, user)] = secret

    def get_password(self, service, user):
        return self.items.get((service, user))


def test_keychain_vault_round_trip_and_service_names():
    backend = FakeKeyring()
    vault = KeychainVault(backend)
    vault.set("instahyre", " owner@example.com ", "TEST_FAKE_TOKEN_ONLY")
    assert vault.get("instahyre") == ("owner@example.com", "TEST_FAKE_TOKEN_ONLY") and vault.has("instahyre")
    assert ("automated-apply:instahyre", "__account__") in backend.items
    assert vault.get("wellfound") is None
    with pytest.raises(ValueError):
        vault.service("../etc")
    with pytest.raises(ValueError):
        vault.set("instahyre", "", "x")


def test_set_portal_cred_cli_stores_in_vault_without_echoing_the_secret(capsys):
    vault = MemoryVault()
    code = cli.set_portal_cred_command("instahyre", vault, prompt=lambda _: "owner@example.com",
                                       secret=lambda _: "TEST_FAKE_TOKEN_ONLY")
    out = capsys.readouterr().out
    assert code == 0 and vault.get("instahyre") == ("owner@example.com", "TEST_FAKE_TOKEN_ONLY")
    assert "TEST_FAKE_TOKEN_ONLY" not in out and "automated-apply:instahyre" in out
    assert cli.set_portal_cred_command("greenhouse", vault) == 2  # no password login for ATS boards
