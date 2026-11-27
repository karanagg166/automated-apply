"""`PortalConfig` and the state / session / navigation base of `InteractivePortalAdapter`."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import AuthStatus, SessionCheck
from backend.app.browser_v2.adapters.shared.apply_flow import CONFIRM_TEXT
from backend.app.browser_v2.adapters.shared.dom_scripts import PROBE_JS
from backend.app.browser_v2.adapters.shared.form_filler import HostedFormFiller
from backend.app.browser_v2.adapters.shared.text import NoteComposer
from backend.app.browser_v2.answers import ScreeningResolver


# --- config-driven interactive portal adapter -------------------------------------------------
@dataclass(frozen=True)
class PortalConfig:
    platform: str
    label: str
    hosts: tuple[str, ...]
    home_url: str
    job_path: str  # JS regex source; group 1 = stable job id
    logged_in: str  # CSS selector list proving an authenticated session
    login_form: str = 'input[type=password], form[action*="login" i], [class*="login-form" i]'
    login_paths: tuple[str, ...] = ("/login", "/signin", "/sign_in", "/users/sign_in", "/nlogin", "/auth")
    login_hosts: tuple[str, ...] = ()
    apply_text: str = r"^(?:apply|apply now|easy apply|quick apply|1-click apply|i'?m interested|interested)$"
    applied_text: str = r"^(?:applied|already applied|application sent)$"
    external_text: str = r"apply on company (?:site|website)|apply externally|company website"
    confirm_text: str = CONFIRM_TEXT
    limit_text: str = (r"(?:daily|today'?s?)\s+(?:apply|application)s?\s+(?:limit|quota)|reached\s+(?:the|your)\s+"
                       r"(?:daily\s+|maximum\s+)?(?:apply\s+|application\s+)?limit|apply\s+limit\s+(?:reached|exceeded)|"
                       r"you can(?:not|'t) apply to (?:more|any more)")
    dialog_selectors: tuple[str, ...] = ("[role=dialog]", "[aria-modal=true]", ".modal.show", ".modal.in",
                                         "[class*='modal' i]", "[class*='Modal']", "[class*='drawer' i]")
    # Keep True: a dry-run then never clicks Apply, so it can never cause an unrecorded
    # submission. (False would let dry-runs open the form; only for portals where Apply
    # provably cannot submit.)
    apply_click_may_submit: bool = True
    # True when Apply navigates to a full-page application form (no modal), e.g. Internshala.
    form_page_after_apply: bool = False
    # True when the Apply click only OPENS a form/modal and can never send an application by itself
    # (Wellfound note modal, Internshala form page): until a submit control is clicked, an error or a
    # missing form is a retryable FAILED, never a never-replay SUBMISSION_UNKNOWN fence.
    apply_opens_form: bool = False
    # Text of an after-click modal saying the employer takes applications elsewhere (live 2026-11-27
    # Wellfound: "Applications to this job are managed outside of Wellfound ... Apply on website").
    external_modal_text: str | None = None
    # Live 2026-11-26: the single primary Apply control when a page repeats equivalent CTAs, and the
    # precise company element when a generic [class*=company] container also holds the title.
    apply_selector: str | None = None
    company_selector: str | None = None
    # CSS that proves search results have rendered (logged-in SPAs hydrate after DOMContentLoaded).
    results_selector: str | None = None
    # Phase 8: a control that is the portal's apply UI but not yet calibrated for automation
    # (live YC 2026-11-26: "Change status to apply" status menu) -> apply_control_unsupported_ui.
    unsupported_apply_text: str | None = None


class PortalAdapterBase:
    """State, session check and navigation helpers shared by the interactive portal mixins."""

    config: PortalConfig

    def __init__(self, *, answerer: ScreeningResolver | None = None, composer: NoteComposer | None = None,
                 settle_ms: int = 1500, refresh_wait_ms: int = 3000, jitter: tuple[float, float] = (0.8, 2.2),
                 receipts_root: Path | None = None, confirm_timeout_s: float = 12.0) -> None:
        self.settle_ms = settle_ms
        self.refresh_wait_ms = refresh_wait_ms
        self.jitter = jitter
        self.receipts_root = receipts_root
        self.confirm_timeout_s = confirm_timeout_s
        self.composer = composer
        self.last_discovery_blocked: str | None = None
        self._answerer = answerer
        self.filler = HostedFormFiller(answerer=answerer, composer=composer, jitter=(0, 0) if jitter[1] == 0
                                       else (0.2, 0.6))

    @property
    def platform(self) -> str:
        return self.config.platform

    # The service rebinds `answerer` when the AI runtime is available.
    @property
    def answerer(self) -> ScreeningResolver | None:
        return self._answerer

    @answerer.setter
    def answerer(self, value: ScreeningResolver | None) -> None:
        self._answerer = value
        self.filler.answerer = value

    # --- navigation helpers ------------------------------------------------------------
    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def _pause(self) -> None:
        if self.jitter[1] > 0:
            await asyncio.sleep(random.uniform(*self.jitter))

    async def _wait_for_results(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Live 2026-11-26: logged-in SPAs (YC, Naukri) render job links well after DOMContentLoaded."""
        try:
            await page.wait_for_function(
                "([pattern, hosts, sel]) => (sel && document.querySelector(sel)) || [...document.querySelectorAll('a[href]')]"
                ".some(a => { try { const u = new URL(a.href, location.href); return hosts.includes(u.hostname) && "
                "new RegExp(pattern).test(u.pathname); } catch (e) { return false; } }) || "
                "/no (?:jobs|results|matching)/i.test(document.body ? document.body.innerText : '')",
                arg=[self.config.job_path, list(self.config.hosts), self.config.results_selector],
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - timeout: parse whatever rendered (possibly none)
            return

    async def _probe(self, page: Any) -> dict[str, Any]:
        return await page.evaluate(PROBE_JS, {"loggedIn": self.config.logged_in, "loginForm": self.config.login_form})

    def classify_auth(self, probe: dict[str, Any]) -> str:
        parts = urlsplit(str(probe.get("url", "")))
        path, host = parts.path.lower(), (parts.hostname or "").lower()
        if probe.get("challenge"):
            return "challenge"
        if probe.get("otp"):
            return "otp"
        if probe.get("loggedIn") and host in self.config.hosts:
            return "ok"
        if host in self.config.login_hosts or any(path.startswith(p) for p in self.config.login_paths) \
                or probe.get("loginForm"):
            return "login"
        return "unknown"

    async def _wait_for_auth_markers(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Cold SPA loads render the logged-in nav late (live: YC/Naukri flipped OK <-> UNKNOWN)."""
        try:
            await page.wait_for_function(
                "([a, b]) => { try { return !!(document.querySelector(a) || document.querySelector(b)); }"
                " catch (e) { return true; } }", arg=[self.config.logged_in, self.config.login_form],
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001, S110 - classify whatever rendered
            pass

    async def check_session(self, page: Any) -> SessionCheck:
        await self._goto(page, self.config.home_url)
        await self._wait_for_auth_markers(page)
        first = self.classify_auth(await self._probe(page))
        if first == "ok":
            return SessionCheck(AuthStatus.OK)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(self.refresh_wait_ms)
        await self._goto(page, self.config.home_url)
        await self._wait_for_auth_markers(page)
        second = self.classify_auth(await self._probe(page))
        details = {"first": first, "second": second}
        if second == "ok":
            return SessionCheck(AuthStatus.OK, refreshed=True, details=details)
        if second in {"login", "otp", "challenge"}:
            return SessionCheck(AuthStatus.AUTH_REQUIRED, refreshed=True, reason=second, details=details)
        return SessionCheck(AuthStatus.UNKNOWN, refreshed=True, reason="logged_in_indicator_missing", details=details)
