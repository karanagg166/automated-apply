"""Headful Playwright persistent context on the dedicated Brave profile.

One worker tab, asset blocking, and a graceful recycle that only happens
between jobs. Designed to keep running while the screen is locked.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2 import profile as brave_profile

LAUNCH_ARGS = (
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--no-first-run",
    "--no-default-browser-check",
)
IGNORE_DEFAULT_ARGS = ("--enable-automation",)
RECYCLE_AFTER_SEC = 3 * 60 * 60

# Keep portal logins across browser restarts (owner request 2026-11-26). Live test: Chromium under
# Playwright drops SESSION-only cookies on every restart regardless of "continue where you left
# off", so the job-portal session cookies are snapshotted after each job / on close and restored at
# launch. Scoped to portal hosts; stored 0600 inside the 0700 dedicated profile directory.
SESSION_COOKIE_FILE = "aa-portal-session-cookies.json"
MAX_SESSION_COOKIES = 500
PORTAL_COOKIE_DOMAINS = (
    "naukri.com", "instahyre.com", "internshala.com", "wellfound.com", "angel.co", "workatastartup.com",
    "ycombinator.com", "weworkremotely.com", "himalayas.app", "hiring.cafe", "hiringcafe.com",
    "greenhouse.io", "lever.co",
)


# Background mode (owner request 2026-11-26): the automation Brave must never steal focus from the
# app the owner is working in. Headful is kept (anti-bot), but the previously frontmost app is
# re-activated right after Brave launches / opens a window. Disable with
# AUTOMATED_APPLY_BROWSER_BACKGROUND=0 (e.g. when watching a run).
BACKGROUND_VARIABLE = "AUTOMATED_APPLY_BROWSER_BACKGROUND"
BRAVE_BUNDLE_IDS = frozenset({"com.brave.Browser", "com.brave.Browser.beta", "com.brave.Browser.nightly"})
_BUNDLE = re.compile(r'bundleID="([^"]+)"')


def background_mode() -> bool:
    return sys.platform == "darwin" and (os.environ.get(BACKGROUND_VARIABLE) or "1").strip().lower() not in {
        "0", "false", "no", "off"}


def front_bundle_id(run: Any = subprocess.run) -> str | None:
    """Bundle id of the frontmost macOS app via lsappinfo (no Automation/TCC permission needed)."""
    try:
        front = run(["/usr/bin/lsappinfo", "front"], capture_output=True, text=True, timeout=3).stdout.strip()
        info = run(["/usr/bin/lsappinfo", "info", "-only", "bundleid", front], capture_output=True, text=True,
                   timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = _BUNDLE.search(info or "")
    return match.group(1) if match else None


def refocus(bundle_id: str | None, run: Any = subprocess.run) -> bool:
    """Give focus back to the owner's app (`open -b` needs no Apple Events permission)."""
    if not bundle_id or bundle_id in BRAVE_BUNDLE_IDS:
        return False
    try:
        run(["/usr/bin/open", "-b", bundle_id], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def is_portal_cookie(cookie: dict[str, Any]) -> bool:
    domain = str(cookie.get("domain") or "").lstrip(".").lower()
    return any(domain == d or domain.endswith("." + d) for d in PORTAL_COOKIE_DOMAINS)

BLOCKED_RESOURCE_TYPES = frozenset({"media", "font"})
# Heavy analytics/ad hosts. Auth, CAPTCHA and portal first-party hosts are never blocked.
BLOCKED_HOST_SUFFIXES = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "facebook.net", "connect.facebook.net",
    "hotjar.com", "clarity.ms", "taboola.com", "outbrain.com", "criteo.com", "criteo.net",
    "adnxs.com", "amazon-adsystem.com", "scorecardresearch.com", "quantserve.com",
    "moengage.com", "clevertap-prod.com", "webengage.com", "branch.io", "mixpanel.com",
    "segment.io", "newrelic.com", "nr-data.net", "bat.bing.com", "ads.linkedin.com",
)
NEVER_BLOCK_HOST_SUFFIXES = (
    "recaptcha.net", "hcaptcha.com", "challenges.cloudflare.com", "accounts.google.com",
    "gstatic.com", "www.google.com", "apis.google.com",
)


def should_block(url: str, resource_type: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == s or host.endswith("." + s) for s in NEVER_BLOCK_HOST_SUFFIXES):
        return False
    if resource_type in BLOCKED_RESOURCE_TYPES:
        return True
    return any(host == s or host.endswith("." + s) for s in BLOCKED_HOST_SUFFIXES)


class RecycleRefused(RuntimeError):
    pass


class BraveBrowserManager:
    """Owns the persistent context. Not thread-safe; use from one event loop."""

    def __init__(self, *, user_data_dir: Path | None = None, executable: Path | None = None,
                 block_assets: bool = True, playwright_factory: Any = None) -> None:
        self.user_data_dir = user_data_dir or brave_profile.profile_dir()
        self.executable = executable or brave_profile.brave_executable()
        self.block_assets = block_assets
        self._playwright_factory = playwright_factory
        self._playwright: Any = None
        self._context: Any = None
        self._worker: Any = None
        self.browser_started_at: float | None = None
        self._job_active = False
        self._lock = asyncio.Lock()
        self.background = background_mode()

    def launch_options(self) -> dict[str, Any]:
        return {
            "user_data_dir": str(self.user_data_dir),
            "executable_path": str(self.executable),
            "headless": False,
            "args": list(LAUNCH_ARGS),
            "ignore_default_args": list(IGNORE_DEFAULT_ARGS),
            "no_viewport": True,
            "accept_downloads": False,
        }

    @property
    def running(self) -> bool:
        return self._context is not None

    async def start(self) -> Any:
        async with self._lock:
            if self._context is not None:
                return self._context
            brave_profile.ensure_profile_dir(self.user_data_dir)
            brave_profile.assert_profile_free(self.user_data_dir)
            brave_profile.ensure_persistent_preferences(self.user_data_dir)  # stay logged in across restarts
            if not self.executable.exists():
                raise brave_profile.ProfileError(f"brave_executable_missing:{self.executable}")
            if self._playwright_factory is None:
                from playwright.async_api import async_playwright

                self._playwright_factory = async_playwright
            self._playwright = await self._playwright_factory().start()
            options = self.launch_options()
            user_data_dir = options.pop("user_data_dir")
            owner_app = await asyncio.to_thread(front_bundle_id) if self.background else None
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir, **options)
            if owner_app:
                await self._return_focus(owner_app)
            if self.block_assets:
                await self._context.route("**/*", self._route)
            self.browser_started_at = time.monotonic()
            pages = self._context.pages
            self._worker = pages[0] if pages else await self._context.new_page()
            await self.tidy_tabs()
            await self.restore_session_cookies()
            return self._context

    # --- portal session-cookie persistence ------------------------------------------------
    def _session_file(self) -> Path:
        return Path(self.user_data_dir) / SESSION_COOKIE_FILE

    async def snapshot_session_cookies(self) -> int:
        """Save portal session-only cookies (expires == -1) so a restart does not log out."""
        if self._context is None:
            return 0
        try:
            cookies = [c for c in await self._context.cookies()
                       if is_portal_cookie(c) and float(c.get("expires", -1) or -1) < 0][:MAX_SESSION_COOKIES]
            path = self._session_file()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cookies))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            return len(cookies)
        except Exception:  # noqa: BLE001 - persistence is best effort, never breaks a job
            return 0

    async def restore_session_cookies(self) -> int:
        """Re-add saved portal session cookies that the restart dropped (never overwrites live ones)."""
        path = self._session_file()
        if self._context is None or not path.is_file():
            return 0
        try:
            saved = json.loads(path.read_text())
            live = {(c["name"], c["domain"], c["path"]) for c in await self._context.cookies()}
            missing = [{k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite")
                        if k in c}
                       for c in saved if isinstance(c, dict) and is_portal_cookie(c)
                       and (c.get("name"), c.get("domain"), c.get("path")) not in live][:MAX_SESSION_COOKIES]
            if missing:
                await self._context.add_cookies(missing)
            return len(missing)
        except Exception:  # noqa: BLE001
            return 0

    async def _route(self, route: Any) -> None:
        request = route.request
        if should_block(request.url, request.resource_type):
            await route.abort()
        else:
            await route.continue_()

    async def _return_focus(self, owner_app: str) -> None:
        """Brave activates itself a moment after launch on macOS: hand focus back a few times.
        lsappinfo / `open -b` run in a thread: the worker loop also serves Telegram."""
        for delay in (0.0, 0.4, 1.2):
            await asyncio.sleep(delay)
            if await asyncio.to_thread(front_bundle_id) in BRAVE_BUNDLE_IDS:
                await asyncio.to_thread(refocus, owner_app)

    async def page(self) -> Any:
        """The single reusable worker tab."""
        await self.start()
        if self._worker is None or self._worker.is_closed():
            owner_app = await asyncio.to_thread(front_bundle_id) if self.background else None
            self._worker = await self._context.new_page()
            if owner_app:
                await self._return_focus(owner_app)
        return self._worker

    async def tidy_tabs(self) -> int:
        """Close popups and stray tabs so only the worker tab remains."""
        if self._context is None:
            return 0
        closed = 0
        for page in list(self._context.pages):
            if page is not self._worker and not page.is_closed():
                await page.close()
                closed += 1
        return closed

    @asynccontextmanager
    async def job(self) -> AsyncIterator[Any]:
        """Mark a job in flight; recycling is refused until it ends."""
        page = await self.page()
        self._job_active = True
        try:
            yield page
        finally:
            self._job_active = False
            await self.snapshot_session_cookies()
            await self.tidy_tabs()

    def age_seconds(self) -> float:
        return 0.0 if self.browser_started_at is None else time.monotonic() - self.browser_started_at

    async def maybe_recycle_between_jobs(self, max_age_sec: int = RECYCLE_AFTER_SEC) -> bool:
        if self._job_active:
            return False
        if not self.running or self.age_seconds() < max_age_sec:
            return False
        await self.recycle()
        return True

    async def recycle(self) -> None:
        if self._job_active:
            raise RecycleRefused("job_in_flight")
        await self.close()
        await self.start()

    async def close(self) -> None:
        async with self._lock:
            context, playwright = self._context, self._playwright
            self._context = self._worker = self._playwright = None
            self.browser_started_at = None
            if context is not None:
                self._context = context  # snapshot needs the live context
                await self.snapshot_session_cookies()
                self._context = None
                await context.close()
            if playwright is not None:
                await playwright.stop()
