"""Naukri auth classification, session check (with one refresh) and live OTP entry."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import AuthStatus, SessionCheck
from backend.app.browser_v2.adapters.naukri.base import NaukriAdapterBase
from backend.app.browser_v2.adapters.naukri.constants import HOME_URL, ORIGIN, OTP_VALUE
from backend.app.browser_v2.adapters.naukri.dom_scripts import (
    AUTH_PROBE_JS,
    OTP_STATE_JS,
)


def classify_auth(probe: dict[str, Any]) -> str:
    path = urlsplit(str(probe.get("url", ""))).path.lower()
    if probe.get("challenge"):
        return "challenge"
    if probe.get("otp"):
        return "otp"
    if "/nlogin" in path or path.startswith("/login") or probe.get("loginForm"):
        return "login"
    if probe.get("loggedIn") and path.startswith("/mnjuser"):
        return "ok"
    return "unknown"


class NaukriAuthMixin(NaukriAdapterBase):
    """Navigation, auth probe, session check and OTP recovery."""

    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def _probe(self, page: Any) -> dict[str, Any]:
        return await page.evaluate(AUTH_PROBE_JS)

    async def _cookie_names(self, page: Any) -> set[str]:
        try:
            cookies = await page.context.cookies(ORIGIN)
        except Exception:  # noqa: BLE001 - best-effort probe; DOM checks still decide auth
            return set()
        return {c.get("name") for c in cookies}

    async def _wait_for_auth_markers(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Live 2026-11-27 (launchd worker, cold Brave): the logged-in header renders after
        DOMContentLoaded, so an early probe said UNKNOWN and the whole portal was skipped."""
        try:
            await page.wait_for_function(
                "() => !!document.querySelector('.nI-gNb-drawer__icon,.nI-gNb-icon-img,.nI-gNb-info,.nI-gNb-drawer,"
                "a[href*=\"/mnjuser/profile\"],.view-profile-wrapper,input[type=password],#usernameField,"
                "input[autocomplete=\"one-time-code\"]') || /nlogin|login/i.test(location.pathname)",
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001, S110 - classify whatever rendered
            pass

    async def check_session(self, page: Any) -> SessionCheck:
        """Logged-in check that lets nauk_rt renew an expired nauk_at before failing."""
        await self._goto(page, HOME_URL)
        await self._wait_for_auth_markers(page)
        first = classify_auth(await self._probe(page))
        if first == "ok":
            return SessionCheck(AuthStatus.OK)
        # One clean reload + wait gives Naukri's refresh-token flow a chance,
        # then the authenticated page is requested again.
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(self.refresh_wait_ms)
        await self._goto(page, HOME_URL)
        await self._wait_for_auth_markers(page)
        second = classify_auth(await self._probe(page))
        cookies = await self._cookie_names(page)
        details = {"first": first, "second": second,
                   "has_refresh_cookie": "nauk_rt" in cookies, "has_access_cookie": "nauk_at" in cookies}
        if second == "ok":
            return SessionCheck(AuthStatus.OK, refreshed=True, details=details)
        if second in {"login", "otp", "challenge"}:
            return SessionCheck(AuthStatus.AUTH_REQUIRED, refreshed=True, reason=second, details=details)
        return SessionCheck(AuthStatus.UNKNOWN, refreshed=True, reason="logged_in_indicator_missing",
                            details=details)

    # --- Phase 6A: live OTP entry -----------------------------------------------------------
    @staticmethod
    def otp_from_answers(hitl_answers: dict[str, str] | None) -> str | None:
        """Newest owner answer that is a 4-8 digit code (resolved OTP HITL rows)."""
        for answer in reversed(list((hitl_answers or {}).values())):
            match = OTP_VALUE.match(answer or "")
            if match:
                return match.group(1)
        return None

    async def obtain_otp(self, hitl_answers: dict[str, str] | None, since: datetime) -> tuple[str | None, str]:
        code = self.otp_from_answers(hitl_answers)
        if code:
            return code, "hitl_owner_answer"
        if self.otp_provider is not None:
            try:
                fetched = await self.otp_provider(self.platform, since)
            except Exception:  # noqa: BLE001 - mail outage: fall back to the OTP HITL
                fetched = None
            if fetched and OTP_VALUE.match(fetched):
                return fetched.strip(), "email_otp"
        return None, "none"

    async def enter_otp(self, page: Any, code: str) -> bool:
        """Type the code into Naukri's OTP box(es) and press Verify. True when the OTP screen clears."""
        if not OTP_VALUE.match(code or ""):
            return False
        state = await page.evaluate(OTP_STATE_JS)
        if not state.get("boxes"):
            return False
        boxes = page.locator('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i],'
                             'input[class*="otp" i]')
        digits = code.strip()
        if state["boxes"] == 1:
            await boxes.first.fill(digits)
        else:  # one box per digit
            for index, digit in enumerate(digits[: state["boxes"]]):
                await boxes.nth(index).fill(digit)
        await page.wait_for_timeout(300)
        verify = page.locator("button,[role=button],input[type=submit]").filter(
            has_text=re.compile(r"^\s*(verify|submit|continue|login|proceed|confirm)\s*$", re.IGNORECASE))
        if await verify.count() >= 1:
            await verify.first.click()
        else:
            await boxes.last.press("Enter")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while loop.time() < deadline:
            await page.wait_for_timeout(400)
            after = await page.evaluate(OTP_STATE_JS)
            if after.get("invalid"):
                return False
            if not after.get("boxes"):
                return True
        return False

    async def recover_otp(self, page: Any, hitl_answers: dict[str, str] | None) -> tuple[bool, str]:
        since = datetime.now(UTC) - timedelta(minutes=3)
        code, source = await self.obtain_otp(hitl_answers, since)
        if code is None:
            return False, "otp_unavailable"
        return await self.enter_otp(page, code), source
