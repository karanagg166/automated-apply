"""Single-process, opt-in dedicated browser. No CDP, cookies, arbitrary JS or tab API.

All automation writes and form navigation are blocked at both DOM and network boundaries.
Take Over is an explicit relinquishment of automation to the owner, never a submission report.
"""

import asyncio
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

from backend.app.browser.contracts import DetectedField
from backend.app.services.applications.resume_selector import digest

DETECT = Path(__file__).with_name("dom.js").read_text()
GUARD = """(() => {
  window.__aaManual = false;
  const stop = e => { if (!window.__aaManual) {e.preventDefault(); e.stopImmediatePropagation();} };
  document.addEventListener('submit', stop, true);
  document.addEventListener('click', e => {if(e.target.closest('button[type="submit"],input[type="submit"],button:not([type])')) stop(e);}, true);
  document.addEventListener('keydown', e => {if(e.key === 'Enter') stop(e);}, true);
  const submit = HTMLFormElement.prototype.submit;
  const request = HTMLFormElement.prototype.requestSubmit;
  HTMLFormElement.prototype.submit = function(...a){if(window.__aaManual) return submit.apply(this,a);};
  HTMLFormElement.prototype.requestSubmit = function(...a){if(window.__aaManual) return request.apply(this,a);};
})();"""


def origin(url):
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
            raise ValueError()
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
    except ValueError:
        raise HTTPException(422, "Invalid browser destination") from None


async def validate_destination(url, settings, *, return_addresses=False):
    target = origin(url)
    parsed = urlsplit(url)
    restricted = {
        "linkedin.com",
        "naukri.com",
        "wellfound.com",
        "instahyre.com",
        "internshala.com",
        "accounts.google.com",
    }
    if any(
        parsed.hostname == host or parsed.hostname.endswith("." + host)
        for host in restricted
    ):
        raise HTTPException(
            403,
            "This platform requires manual handoff; no portal browser adapter is verified",
        )
    if target not in settings.BROWSER_ALLOWED_ORIGINS:
        raise HTTPException(
            403, "Destination has no configured browser permission; use manual handoff"
        )
    mock = settings.ENVIRONMENT == "testing" and parsed.hostname == "127.0.0.1"
    if parsed.scheme != "https" and not (mock and parsed.scheme == "http"):
        raise HTTPException(422, "HTTPS is required")
    if len(url) > 2048 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise HTTPException(422, "Invalid browser URL")
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except OSError:
        raise HTTPException(422, "Browser destination cannot be resolved") from None
    if not addresses or (
        not mock and any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    ):
        raise HTTPException(403, "Private network browser access is forbidden")
    return (
        (target, sorted({a[4][0] for a in addresses})) if return_addresses else target
    )


class BrowserSession:
    def __init__(self, context, page, target, url, playwright):
        self.context, self.page = context, page
        self.target, self.url, self.playwright = target, url, playwright
        self.manual, self.navigating = False, True
        self.signature = None
        self.context_evidence = {}
        self.fields = []

    async def route(self, route):
        request = route.request
        try:
            allowed = origin(request.url) == self.target
        except HTTPException:
            allowed = False
        if not self.manual:
            allowed = allowed and request.method in {"GET", "HEAD"}
            if request.is_navigation_request():
                allowed = allowed and self.navigating and request.url == self.url
        if allowed:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def scan(self):
        if self.page.is_closed() or self.page.url != self.url:
            raise HTTPException(
                409,
                "Browser disconnected or destination changed; take over and reanalyze",
            )
        result = await self.page.evaluate(DETECT)
        if result["blocked"]:
            raise HTTPException(
                409, "Access challenge or authentication required; take over manually"
            )
        self.context_evidence = {
            "url": self.page.url,
            "title": result["title"],
            "heading": result["heading"],
        }
        self.signature = digest(
            {"form": result["signature"], "context": self.context_evidence}
        )
        self.fields = [
            DetectedField.model_validate(f).model_dump() for f in result["fields"]
        ]
        return self.fields, ["Embedded forms require manual review"] if result[
            "has_frames"
        ] else []

    async def unchanged(self, signature):
        # scan assigns fresh opaque handles; use the fresh handles only after structure comparison.
        fields, warnings = await self.scan()
        if signature != self.signature:
            raise HTTPException(409, "Form changed; analyze again before filling")
        return fields, warnings

    async def fill(self, field, value=None, upload=None):
        element = self.page.locator(f'[data-aa-field="{field["key"]}"]')
        if await element.count() != 1:
            raise HTTPException(409, "Form changed; analyze again")
        if field["kind"] == "file":
            await element.set_input_files(upload)
        elif field["kind"] == "select":
            await element.select_option(label=value)
        else:
            await element.fill(value)
        # DOM validity is evidence of completeness, never proof of submission.
        return await element.evaluate("(e) => e.validity ? e.validity.valid : false")

    async def close(self):
        await self.context.close()
        await self.playwright.stop()


class LocalBrowser:
    def __init__(self):
        self.sessions = {}
        self.opening = set()
        self.locks = {}

    def lock(self, packet_id):
        return self.locks.setdefault(str(packet_id), asyncio.Lock())

    async def open(self, packet_id, url, settings):
        target, addresses = await validate_destination(
            url, settings, return_addresses=True
        )
        key = str(packet_id)
        if key in self.sessions:
            return self.sessions[key]
        if len(self.sessions) + len(self.opening) >= 2:
            raise HTTPException(
                429, "At most two dedicated browser sessions may be open"
            )
        root = Path(settings.BROWSER_PROFILE_ROOT).absolute()
        # Refuse existing symlinks at every path component, including the profile itself.
        for component in [root, *root.parents]:
            if component.is_symlink():
                raise HTTPException(
                    422, "Browser profile root must not contain symlinks"
                )
        marker = root / ".automated-apply-profile-root"
        if root.exists() and not marker.is_file():
            raise HTTPException(
                422, "Refusing an existing unapproved browser profile root"
            )
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.touch(mode=0o600)
        os.chmod(root, 0o700)
        directory = root / key
        if directory.is_symlink():
            raise HTTPException(422, "Browser profile must not be a symlink")
        directory.mkdir(exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        from playwright.async_api import async_playwright

        # Reserve admission before the first browser-launch await, including other packets.
        self.opening.add(key)
        playwright = context = None
        try:
            playwright = await async_playwright().start()
            context = await playwright.chromium.launch_persistent_context(
                str(directory),
                # Pin the approved hostname to its validated address for the entire session.
                # TLS still verifies the original hostname; no proxy/DNS rebind can reach LAN.
                args=[
                    f"--host-resolver-rules=MAP {urlsplit(url).hostname} {addresses[0]}",
                    "--dns-over-https-mode=off",
                    "--no-proxy-server",
                ],
                channel=settings.BROWSER_CHANNEL,
                headless=settings.BROWSER_HEADLESS,
                accept_downloads=False,
                service_workers="block",
                timeout=30000,
            )
            await context.add_init_script(GUARD)
            await context.route_web_socket("**/*", lambda websocket: websocket.close())
            context.on(
                "page", lambda page: page.on("popup", lambda popup: popup.close())
            )
            # A newly owned profile only; never attach to pre-existing tabs or profiles.
            page = await context.new_page()
            for old in context.pages:
                if old != page:
                    await old.close()
            page.set_default_timeout(5000)
            session = BrowserSession(context, page, target, url, playwright)
            await context.route("**/*", session.route)
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=15000
            )
            session.navigating = False
            if response is None or response.status >= 400:
                raise HTTPException(409, "Destination unavailable; take over manually")
            self.sessions[key] = session
            return session
        except BaseException:
            if context:
                await context.close()
            if playwright:
                await playwright.stop()
            raise
        finally:
            self.opening.discard(key)

    async def close(self, packet_id):
        session = self.sessions.pop(str(packet_id), None)
        if session:
            await session.close()


browser = LocalBrowser()
