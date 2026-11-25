"""Headful Playwright persistent context on the dedicated Brave profile.

One worker tab, asset blocking, and a graceful recycle that only happens
between jobs. Designed to keep running while the screen is locked.
"""

from __future__ import annotations

import asyncio
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
            if not self.executable.exists():
                raise brave_profile.ProfileError(f"brave_executable_missing:{self.executable}")
            if self._playwright_factory is None:
                from playwright.async_api import async_playwright

                self._playwright_factory = async_playwright
            self._playwright = await self._playwright_factory().start()
            options = self.launch_options()
            user_data_dir = options.pop("user_data_dir")
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir, **options)
            if self.block_assets:
                await self._context.route("**/*", self._route)
            self.browser_started_at = time.monotonic()
            pages = self._context.pages
            self._worker = pages[0] if pages else await self._context.new_page()
            await self.tidy_tabs()
            return self._context

    async def _route(self, route: Any) -> None:
        request = route.request
        if should_block(request.url, request.resource_type):
            await route.abort()
        else:
            await route.continue_()

    async def page(self) -> Any:
        """The single reusable worker tab."""
        await self.start()
        if self._worker is None or self._worker.is_closed():
            self._worker = await self._context.new_page()
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
                await context.close()
            if playwright is not None:
                await playwright.stop()
