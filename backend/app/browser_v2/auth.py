"""Smart auto re-login (Phase 6A), tried once before an AUTH_REQUIRED Telegram HITL.

Order per portal (max ONE attempt per portal per 30 minutes, so a broken login can
never turn into a bot-lock loop):
  1. Keychain email + password (macOS Keychain via `keyring`, service
     `automated-apply:<portal>`; never .env, never Postgres). If the portal then asks for
     an EMAIL OTP, `MailReadService.poll_otp` reads it (<= 45 s) and it is typed in.
  2. Trusted "Continue with Google" chip: only when the dedicated Brave profile already
     holds a signed-in Google session. HARD GUARDRAIL: nothing is EVER typed on
     accounts.google.com; a Google password / 2FA / challenge screen aborts at once.
  3. Anything else (SMS OTP, hard CAPTCHA, unknown page) -> HITL (only that portal pauses).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

SERVICE_PREFIX = "automated-apply:"
ACCOUNT_KEY = "__account__"
COOLDOWN = timedelta(minutes=30)
GOOGLE_HOSTS = ("accounts.google.com", "accounts.youtube.com")
EMAIL_INPUT = ('input[type=email], input[name*="email" i], input[id*="email" i], input[name*="username" i], '
               'input[id*="username" i], #usernameField, #ycid-input')
PASSWORD_INPUT = 'input[type=password]'
OTP_INPUT = 'input[autocomplete="one-time-code"], input[name*="otp" i], input[id*="otp" i], input[class*="otp" i]'
SUBMIT_TEXT = re.compile(r"^\s*(?:log ?in|sign ?in|continue|submit|next|proceed|verify)\s*$", re.IGNORECASE)
GOOGLE_BUTTON = re.compile(r"(?:continue|sign ?in|log ?in|login)\s+with\s+google|^\s*google\s*$", re.IGNORECASE)
GOOGLE_DANGER = re.compile(r"/(?:challenge|signin/v2/challenge|v3/signin/challenge|signin/identifier)\b|"
                           r"/speedbump|/signin/rejected", re.IGNORECASE)


class GoogleTypingRefused(RuntimeError):
    """Raised if any code path tries to type into a Google account page."""


@dataclass(frozen=True)
class LoginSpec:
    login_url: str
    password_login: bool = True
    google_sso: bool = False
    two_step_email: bool = False  # email -> Continue -> password


LOGIN_SPECS: dict[str, LoginSpec] = {
    "naukri": LoginSpec("https://www.naukri.com/nlogin/login", google_sso=True),
    "instahyre": LoginSpec("https://www.instahyre.com/login/", google_sso=True),
    "internshala": LoginSpec("https://internshala.com/login/user", google_sso=True),
    "wellfound": LoginSpec("https://wellfound.com/login", google_sso=True),
    "work_at_a_startup": LoginSpec("https://account.ycombinator.com/?continue=https://www.workatastartup.com/"),
    "himalayas": LoginSpec("https://himalayas.app/login", password_login=False, google_sso=True),
}


# --- credential vault -------------------------------------------------------------------------
class Vault(Protocol):
    def get(self, portal: str) -> tuple[str, str] | None: ...

    def set(self, portal: str, username: str, password: str) -> None: ...

    def has(self, portal: str) -> bool: ...


class KeychainVault:
    """macOS Keychain (via `keyring`). Secrets never leave the Keychain except into the portal form."""

    def __init__(self, backend: Any = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> Any:
        if self._backend is None:
            import keyring

            self._backend = keyring
        return self._backend

    @staticmethod
    def service(portal: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", portal):
            raise ValueError("invalid_portal")
        return SERVICE_PREFIX + portal

    def get(self, portal: str) -> tuple[str, str] | None:
        try:
            username = self.backend.get_password(self.service(portal), ACCOUNT_KEY)
            password = self.backend.get_password(self.service(portal), username) if username else None
        except Exception as exc:  # noqa: BLE001 - locked keychain / no backend: no auto-login
            logger.info("keychain read unavailable for %s: %s", portal, type(exc).__name__)
            return None
        return (username, password) if username and password else None

    def set(self, portal: str, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise ValueError("username_and_password_required")
        self.backend.set_password(self.service(portal), ACCOUNT_KEY, username.strip())
        self.backend.set_password(self.service(portal), username.strip(), password)

    def has(self, portal: str) -> bool:
        return self.get(portal) is not None


class MemoryVault:
    def __init__(self, items: dict[str, tuple[str, str]] | None = None) -> None:
        self.items = dict(items or {})

    def get(self, portal: str) -> tuple[str, str] | None:
        return self.items.get(portal)

    def set(self, portal: str, username: str, password: str) -> None:
        self.items[portal] = (username, password)

    def has(self, portal: str) -> bool:
        return portal in self.items


# --- auto login -------------------------------------------------------------------------------
@dataclass(frozen=True)
class AutoLoginResult:
    ok: bool
    method: str  # password | password+email_otp | google_chip | none
    reason: str
    hitl_kind: str | None = None  # AUTH | OTP | CAPTCHA when a human is needed

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "method": self.method, "reason": self.reason, "hitl_kind": self.hitl_kind}


def on_google(page: Any) -> bool:
    host = (urlsplit(str(getattr(page, "url", "") or "")).hostname or "").lower()
    return host in GOOGLE_HOSTS or host.endswith(".google.com")


async def safe_fill(page: Any, selector: str, value: str) -> None:
    """Every credential keystroke goes through here: refuses Google account pages outright."""
    if on_google(page):
        raise GoogleTypingRefused("refusing_to_type_on_google_accounts")
    await page.locator(selector).first.fill(value)


class AutoLogin:
    def __init__(self, vault: Vault | None = None, mail_reader: Any = None, *,
                 clock: Callable[[], datetime] | None = None, cooldown: timedelta = COOLDOWN,
                 otp_timeout_s: float = 45.0, settle_ms: int = 2000, specs: dict[str, LoginSpec] | None = None,
                 owner_email: str | None = None) -> None:
        self.vault = vault or KeychainVault()
        self.mail_reader = mail_reader
        self.clock = clock or (lambda: datetime.now(UTC))
        self.cooldown = cooldown
        self.otp_timeout_s = otp_timeout_s
        self.settle_ms = settle_ms
        self.specs = specs or LOGIN_SPECS
        self.owner_email = owner_email
        self.last_attempt: dict[str, datetime] = {}

    def cooling_down(self, portal: str) -> bool:
        last = self.last_attempt.get(portal)
        return last is not None and self.clock() - last < self.cooldown

    async def attempt(self, portal: str, page: Any, adapter: Any) -> AutoLoginResult:
        spec = self.specs.get(portal)
        if spec is None:
            return AutoLoginResult(False, "none", "auto_login_unsupported", "AUTH")
        if self.cooling_down(portal):
            return AutoLoginResult(False, "none", "auto_login_cooldown", "AUTH")
        self.last_attempt[portal] = self.clock()
        try:
            creds = self.vault.get(portal) if spec.password_login else None
            if creds is not None:
                result = await self._password_login(portal, page, adapter, spec, creds)
                if result.ok or not spec.google_sso or result.hitl_kind in ("CAPTCHA", "OTP"):
                    return result
            if spec.google_sso:
                return await self._google_chip(portal, page, adapter, spec)
            return AutoLoginResult(False, "none", "no_keychain_credentials", "AUTH")
        except GoogleTypingRefused:
            return AutoLoginResult(False, "google_chip", "google_password_screen_refused", "AUTH")
        except Exception as exc:  # noqa: BLE001 - any surprise -> HITL, never a retry loop
            logger.warning("auto-login %s failed: %s", portal, type(exc).__name__)
            return AutoLoginResult(False, "none", "auto_login_error:" + type(exc).__name__, "AUTH")

    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def _click_submit(self, page: Any) -> bool:
        """Click the first VISIBLE submit-like control (hidden earlier steps are skipped)."""
        for locator in (page.locator("button, input[type=submit], [role=button]").filter(has_text=SUBMIT_TEXT),
                        page.locator("input[type=submit], button[type=submit]")):
            for index in range(min(await locator.count(), 10)):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    await candidate.click(timeout=10_000)
                    return True
        return False

    async def _verify(self, adapter: Any, page: Any) -> bool:
        check = await adapter.check_session(page)
        return getattr(check.status, "value", check.status) == "OK"

    async def _visible(self, page: Any, selector: str) -> bool:
        locator = page.locator(selector)
        for index in range(min(await locator.count(), 5)):
            if await locator.nth(index).is_visible():
                return True
        return False

    async def _password_login(self, portal: str, page: Any, adapter: Any, spec: LoginSpec,
                              creds: tuple[str, str]) -> AutoLoginResult:
        username, password = creds
        started = self.clock()
        await self._goto(page, spec.login_url)
        if on_google(page):
            return AutoLoginResult(False, "password", "unexpected_google_page", "AUTH")
        if not await self._visible(page, EMAIL_INPUT):
            return AutoLoginResult(False, "password", "login_form_not_found", "AUTH")
        await safe_fill(page, EMAIL_INPUT, username)
        if spec.two_step_email or not await self._visible(page, PASSWORD_INPUT):
            await self._click_submit(page)
            await page.wait_for_timeout(self.settle_ms)
        if not await self._visible(page, PASSWORD_INPUT):
            return AutoLoginResult(False, "password", "password_field_not_found", "AUTH")
        await safe_fill(page, PASSWORD_INPUT, password)
        await self._click_submit(page)
        await page.wait_for_timeout(self.settle_ms)
        probe = await adapter._probe(page) if hasattr(adapter, "_probe") else {}
        if probe.get("challenge"):
            return AutoLoginResult(False, "password", "captcha_after_login", "CAPTCHA")
        if probe.get("otp") or await self._visible(page, OTP_INPUT):
            if self.mail_reader is None:
                return AutoLoginResult(False, "password", "otp_required_no_mail_reader", "OTP")
            code = await self.mail_reader.poll_otp(portal, started - timedelta(seconds=30),
                                                   timeout_s=self.otp_timeout_s)
            if not code:
                return AutoLoginResult(False, "password", "email_otp_not_received", "OTP")
            await self._enter_otp(page, code)
            if await self._verify(adapter, page):
                return AutoLoginResult(True, "password+email_otp", "logged_in")
            return AutoLoginResult(False, "password+email_otp", "otp_rejected_or_sms_otp", "OTP")
        if await self._verify(adapter, page):
            return AutoLoginResult(True, "password", "logged_in")
        return AutoLoginResult(False, "password", "still_logged_out", "AUTH")

    async def _enter_otp(self, page: Any, code: str) -> None:
        if on_google(page):
            raise GoogleTypingRefused("refusing_to_type_on_google_accounts")
        boxes = page.locator(OTP_INPUT)
        count = await boxes.count()
        if count > 1:
            for index, digit in enumerate(code[:count]):
                await boxes.nth(index).fill(digit)
        else:
            await boxes.first.fill(code)
        await self._click_submit(page)
        await page.wait_for_timeout(self.settle_ms)

    async def _google_chip(self, portal: str, page: Any, adapter: Any, spec: LoginSpec) -> AutoLoginResult:
        await self._goto(page, spec.login_url)
        button = page.locator("button, a, [role=button]").filter(has_text=GOOGLE_BUTTON)
        if await button.count() < 1:
            return AutoLoginResult(False, "google_chip", "google_button_not_found", "AUTH")
        pages_before = len(page.context.pages)
        await button.first.click()
        await page.wait_for_timeout(self.settle_ms)
        google = page.context.pages[-1] if len(page.context.pages) > pages_before else page
        if on_google(google):
            outcome = await self._choose_google_account(google)
            if outcome is not None:
                if google is not page:
                    await google.close()
                return outcome
            # Popup closes itself after the chip; the portal tab finishes the redirect.
            for _ in range(20):
                if google is not page and google.is_closed():
                    break
                if google is page and not on_google(page):
                    break
                await page.wait_for_timeout(500)
        if await self._verify(adapter, page):
            return AutoLoginResult(True, "google_chip", "logged_in")
        return AutoLoginResult(False, "google_chip", "still_logged_out", "AUTH")

    async def _choose_google_account(self, google: Any) -> AutoLoginResult | None:
        """Click the existing signed-in account chip; abort on ANY password/2FA/challenge screen."""
        await google.wait_for_timeout(self.settle_ms)
        if GOOGLE_DANGER.search(urlsplit(google.url).path) or await self._visible(google, PASSWORD_INPUT) \
                or await self._visible(google, "input[type=email], input[type=tel]"):
            return AutoLoginResult(False, "google_chip", "google_password_or_2fa_required", "AUTH")
        chips = google.locator("[data-identifier], [data-email], li [data-authuser]")
        count = await chips.count()
        target = None
        for index in range(min(count, 10)):
            chip = chips.nth(index)
            ident = (await chip.get_attribute("data-identifier")) or (await chip.get_attribute("data-email")) or ""
            if self.owner_email and ident.lower() == self.owner_email.lower():
                target = chip
                break
        if target is None and count == 1:
            target = chips.first
        if target is None:
            return AutoLoginResult(False, "google_chip", "google_account_chip_ambiguous", "AUTH")
        await target.click()
        await google.wait_for_timeout(self.settle_ms)
        if not google.is_closed() and on_google(google):
            if GOOGLE_DANGER.search(urlsplit(google.url).path) or await self._visible(google, PASSWORD_INPUT):
                return AutoLoginResult(False, "google_chip", "google_password_or_2fa_required", "AUTH")
            confirm = google.locator("button").filter(has_text=re.compile(r"^\s*continue\s*$", re.IGNORECASE))
            if await confirm.count() == 1:
                await confirm.first.click()  # "Sign in to <portal>" confirmation only; never "Allow"
                await google.wait_for_timeout(self.settle_ms)
        return None

