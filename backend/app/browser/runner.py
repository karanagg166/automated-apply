"""Single-process, opt-in dedicated browser. No CDP, cookies, arbitrary JS or tab API.

All automation writes and form navigation are blocked at both DOM and network boundaries.
Take Over is an explicit relinquishment of automation to the owner, never a submission report.
"""

import asyncio
import ipaddress
import os
import socket
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException

from backend.app.browser.asset_policy import RESTRICTED_HOSTS, policy
from backend.app.browser.assets import AssetUnavailable, PublicAssets
from backend.app.browser.contracts import DetectedField, StepControl
from backend.app.browser.engine import launch_options
from backend.app.browser.field_policy import manual_only
from backend.app.services.applications.resume_selector import digest

DETECT = Path(__file__).with_name("dom.js").read_text()
GUARD = """(() => {
  window.__aaManual = false;
  window.__aaModeGeneration = -1;
  // A new document starts guarded. Only the runner can report owner takeover;
  // a delayed reply cannot undo a newer explicit pause on this document.
  const readMode = () => {
    if (window.__aaOwnerMode) window.__aaOwnerMode().then(state => {
      if (state.generation >= window.__aaModeGeneration) {
        window.__aaModeGeneration = state.generation;
        window.__aaManual = state.manual;
      }
    }).catch(() => {});
  };
  // Playwright does not promise ordering between binding and user init scripts.
  document.addEventListener('DOMContentLoaded', readMode, {once: true});
  window.__aaSubmissionBlocks = 0;
  const stop = e => { if (!window.__aaManual) {window.__aaSubmissionBlocks++; e.preventDefault(); e.stopImmediatePropagation();} };
  document.addEventListener('submit', stop, true);
  document.addEventListener('click', e => {if(e.target.closest('button[type="submit"],input[type="submit"],button:not([type])')) stop(e);}, true);
  document.addEventListener('keydown', e => {if(e.key === 'Enter') stop(e);}, true);
  const submit = HTMLFormElement.prototype.submit;
  const request = HTMLFormElement.prototype.requestSubmit;
  HTMLFormElement.prototype.submit = function(...a){if(window.__aaManual) return submit.apply(this,a); window.__aaSubmissionBlocks++;};
  HTMLFormElement.prototype.requestSubmit = function(...a){if(window.__aaManual) return request.apply(this,a); window.__aaSubmissionBlocks++;};
})();"""


def origin(url):
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
            raise ValueError()
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
    except ValueError:
        raise HTTPException(422, "Invalid browser destination") from None


async def validate_destination(
    url, settings, *, return_addresses=False, allowed_origins=None
):
    target = origin(url)
    parsed = urlsplit(url)
    if any(
        parsed.hostname == host or parsed.hostname.endswith("." + host)
        for host in RESTRICTED_HOSTS
    ):
        raise HTTPException(
            403,
            "This platform requires manual handoff; no portal browser adapter is verified",
        )
    if target not in (
        settings.BROWSER_ALLOWED_ORIGINS if allowed_origins is None else allowed_origins
    ):
        raise HTTPException(
            403, "Destination has no configured browser permission; use manual handoff"
        )
    mock = settings.ENVIRONMENT == "testing" and parsed.hostname == "127.0.0.1"
    if parsed.scheme != "https" and not (mock and parsed.scheme == "http"):
        raise HTTPException(422, "HTTPS is required")
    if len(url) > 2048 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise HTTPException(422, "Invalid browser URL")
    try:
        async with asyncio.timeout(5):
            addresses = await asyncio.get_running_loop().getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
    except (OSError, TimeoutError):
        raise HTTPException(422, "Browser destination cannot be resolved") from None
    if not addresses or (
        not mock and any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    ):
        raise HTTPException(403, "Private network browser access is forbidden")
    return (
        (target, sorted({a[4][0] for a in addresses})) if return_addresses else target
    )


class BrowserResources:
    def __init__(self):
        self.playwright = self.context = None
        self.stop_requested = self.closed = False
        self.lock = asyncio.Lock()
        self.assets = None
        from backend.app.browser.company_source_fetch import SourceFetch

        self.company_source = SourceFetch()

    def checkpoint(self):
        if self.stop_requested:
            raise HTTPException(409, "Dedicated browser opening was cancelled")

    async def close(self):
        self.stop_requested = True
        if self.assets:
            self.assets.seal()
        self.company_source.seal()
        async with self.lock:
            if self.closed or self.playwright is None:
                return
            self.closed = True
            try:
                await self.company_source.close()
                if self.assets:
                    await self.assets.close()
                if self.context:
                    await self.context.close()
            finally:
                await self.playwright.stop()


class BrowserSession:
    def __init__(self, context, page, target, url, playwright, resources):
        self.context, self.page = context, page
        self.resources = resources
        self.cancelled = False
        self.target, self.url, self.playwright = target, url, playwright
        self.manual, self.navigating = False, True
        self.submission = None
        self.signature = None
        self.context_evidence = {}
        self.fields = []
        self.steps = []
        self.blocked_mutations = 0
        self.has_frames = False
        self.in_page_mode = False
        self.blocked_step_requests = 0
        self.mode_generation = self.document_epoch = 0
        self.assisted_document_epoch = 0
        self.paused_for_resume = False
        self.instance_id = uuid4().hex
        self.assets = resources.assets or PublicAssets({})
        self.multi_enabled = False
        self.company_capture = None

    def owner_mode(self, source):
        main = source["page"] == self.page and source["frame"] == self.page.main_frame
        return {"manual": self.manual and main, "generation": self.mode_generation}

    def navigated(self, frame):
        if frame == self.page.main_frame:
            self.document_epoch += 1

    async def set_manual(self, manual):
        # Revoke network permission before awaiting any browser command.
        self.manual = manual
        self.assets.seal()
        self.mode_generation += 1
        if not manual:
            self.in_page_mode = True
        from playwright.async_api import Error

        try:
            await self.page.evaluate(
                """state => {
                  if (state.generation >= (window.__aaModeGeneration ?? -1)) {
                    window.__aaModeGeneration = state.generation;
                    window.__aaManual = state.manual;
                  }
                }""",
                {"manual": manual, "generation": self.mode_generation},
            )
        except Error:
            # Navigation can destroy this context; the next init script reads
            # the current mode from our binding. Closed sessions need recovery.
            if self.page.is_closed():
                raise HTTPException(409, "Dedicated browser disconnected") from None

    async def route(self, route):
        request = route.request
        if self.cancelled:
            await route.abort("blockedbyclient")
            return
        # Reviewed filling and client-only steps cannot save/submit through GET, POST or delayed
        # callbacks. Explicit manual takeover releases this network isolation.
        if self.in_page_mode and not self.manual and self.submission is None:
            self.blocked_step_requests += 1
            if request.method not in {"GET", "HEAD"}:
                self.blocked_mutations += 1
            await route.abort("blockedbyclient")
            return
        try:
            allowed = origin(request.url) == self.target
        except HTTPException:
            allowed = False
        if self.submission and request.method == "POST":
            dispatch = self.submission
            from backend.app.browser.payload import reviewed_multipart

            try:
                exact_body = reviewed_multipart(
                    request.post_data_buffer,
                    request.headers.get("content-type", ""),
                    dispatch["id"],
                    dispatch["digest"],
                )
            except Exception:
                exact_body = False
            allowed = (
                allowed
                and not dispatch["used"]
                and request.url == dispatch["action"]
                and exact_body
            )
            if allowed:
                dispatch["used"] = True
            if allowed:
                await route.continue_()
            else:
                await route.abort("blockedbyclient")
            return
        if self.submission and request.is_navigation_request():
            allowed = (
                allowed
                and request.method == "GET"
                and request.url == self.submission["receipt_url"]
            )
            if allowed:
                await route.continue_()
            else:
                await route.abort("blockedbyclient")
            return
        if not allowed and self.assets.pins:
            try:
                if (
                    self.manual
                    or self.submission
                    or request.method != "GET"
                    or request.is_navigation_request()
                    or request.frame != self.page.main_frame
                ):
                    self.assets.blocked += 1
                    raise AssetUnavailable()
                # Only a public application origin may be forwarded for native
                # CORS negotiation. No browser header/cookie set is forwarded.
                source = request.headers.get("origin")
                source = source if source and origin(source) == self.target else None
                raw, headers = await self.assets.fetch(
                    request.url, request.resource_type, source
                )
                if self.cancelled or self.assets.sealed or self.in_page_mode:
                    self.assets.blocked += 1
                    raise AssetUnavailable()
                await route.fulfill(status=200, body=raw, headers=headers)
            except Exception as error:
                from playwright.async_api import Error

                if not isinstance(error, AssetUnavailable):
                    self.assets.blocked += 1
                with suppress(Error):
                    await route.abort("blockedbyclient")
            return
        if not self.manual:
            allowed = allowed and request.method in {"GET", "HEAD"}
            if request.is_navigation_request():
                allowed = allowed and self.navigating and request.url == self.url
        if allowed:
            await route.continue_()
        else:
            if request.method not in {"GET", "HEAD"}:
                self.blocked_mutations += 1
            await route.abort("blockedbyclient")

    async def scan(self):
        self.assets.seal()
        if not self.manual:
            # Marking DOM handles can run website MutationObservers. Pause before
            # any page evaluation, not only before interactive choice inspection.
            self.in_page_mode = True
        if self.paused_for_resume:
            raise HTTPException(
                409, "Review the current page before resuming assistance"
            )
        if self.cancelled or self.page.is_closed() or self.page.url != self.url:
            raise HTTPException(
                409,
                "Browser disconnected or destination changed; take over and reanalyze",
            )
        result = await self.page.evaluate(DETECT)
        if not self.manual and self.blocked_step_requests:
            raise HTTPException(
                409, "Analysis requires network activity; take over manually"
            )
        if result["blocked"]:
            raise HTTPException(
                409, "Access challenge or authentication required; take over manually"
            )
        if not result["has_frames"]:
            from backend.app.browser.dropdowns import discover

            catalog = await discover(self, result["fields"])
            if catalog:
                result = await self.page.evaluate(DETECT, catalog)
                if result["blocked"] or result["has_frames"]:
                    raise HTTPException(
                        409, "Page changed during choice inspection; take over manually"
                    )
        if not self.manual and self.blocked_step_requests:
            raise HTTPException(
                409, "Analysis requires network activity; take over manually"
            )
        self.context_evidence = {
            "url": self.page.url,
            "title": result["title"],
            "heading": result["heading"],
            "step": result.get("step_heading", ""),
        }
        self.steps = [
            StepControl.model_validate(step).model_dump()
            for step in result.get("steps", [])
        ]
        self.has_frames = result["has_frames"]
        self.signature = digest(
            {
                "form": result["signature"],
                "context": self.context_evidence,
                **(
                    {"multi_policy": self.multi_enabled}
                    if any(
                        f["kind"] in {"multi_select", "checkbox_group"}
                        for f in result["fields"]
                    )
                    else {}
                ),
            }
        )
        self.fields = []
        for field in result["fields"]:
            parsed = DetectedField.model_validate(field).model_dump()
            if manual_only(parsed["question"], *parsed["options"]):
                parsed["supported"] = False
                parsed["manual_reason"] = "Sensitive information or legal attestation requires manual entry"
            if parsed["options_binding"] is None:
                del parsed["options_binding"]
            if (
                not self.multi_enabled
                and parsed["kind"] in {"multi_select", "checkbox_group"}
                and parsed["supported"]
            ):
                parsed["supported"] = False
                parsed["manual_reason"] = (
                    "Multiple selections require enabled database capability; complete manually"
                )
            self.fields.append(parsed)
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
        if self.cancelled:
            raise HTTPException(409, "Browser filling was cancelled")
        # Input/change handlers are untrusted and may submit through any method.
        # Keep isolation after filling, including delayed callbacks, until takeover.
        self.in_page_mode = True
        element = self.page.locator(f'[data-aa-field="{field["key"]}"]')
        if await element.count() != 1:
            raise HTTPException(409, "Form changed; analyze again")
        occupied = await element.evaluate(r"""e => {
          const placeholder = s => !String(s || '').trim() ||
            /^[-–—_\s]*(?:select(?: an? option| one| value)?|choose(?: an? option| one| value)?|please select|none)[-–—_\s.]*$/i.test(String(s).trim());
          if (e.type === 'file') return e.files.length > 0;
          const peers = [...e.querySelectorAll('input[type=radio],input[type=checkbox],[role=radio],[role=checkbox]')];
          if (peers.length) return peers.some(c => c.checked || c.indeterminate || c.getAttribute('aria-checked') === 'true');
          if (e.tagName === 'SELECT') return [...e.selectedOptions].some(o =>
            !o.disabled && (o.index > 0 || (!placeholder(o.textContent) && String(o.value).trim())));
          if (e.matches('[role=combobox]') && e.tagName !== 'INPUT')
            return !placeholder(e.getAttribute('aria-valuetext') || e.getAttribute('data-value'));
          return Boolean(String(e.value || '').trim()) || e.validity?.badInput === true;
        }""")
        if occupied:
            # Preserve owner input, browser autofill and files selected on the page.
            # None means no write occurred; it is distinct from a validated fill.
            return None
        if field["kind"] == "file":
            await element.set_input_files(upload)
        elif field["kind"] in {"multi_select", "checkbox_group"}:
            from backend.app.services.applications.multi_select import decode

            if not self.multi_enabled or not field["supported"]:
                raise HTTPException(
                    409, "Multiple selections are unavailable; use manual handoff"
                )
            selected = decode(value, field["options"], required=field["required"])
            if field["kind"] == "checkbox_group":
                from backend.app.browser.multiple import fill_group

                return await fill_group(self, field, selected)
            await element.select_option(label=selected)
            actual = await element.evaluate(
                "e=>[...e.selectedOptions].map(o=>o.label.trim())"
            )
            return set(actual) == set(selected) and await element.evaluate(
                "e=>e.validity.valid"
            )
        elif field["kind"] == "select":
            await element.select_option(label=value)
        elif field["kind"] == "radio_group":
            choice = element.get_by_role("radio", name=value, exact=True)
            if await choice.count() != 1:
                raise HTTPException(409, "Radio options changed; analyze again")
            if await choice.evaluate("e => e.matches('input[type=radio]')"):
                await choice.check(timeout=5000)
            else:
                await choice.click(timeout=5000)
            selected = await choice.evaluate(
                "e => e.matches('input[type=radio]') ? e.checked && e.validity.valid : e.getAttribute('aria-checked') === 'true'"
            )
            count = await element.evaluate(
                "e => [...e.querySelectorAll('input[type=radio],[role=radio]')].filter(r => r.checked || r.getAttribute('aria-checked') === 'true').length"
            )
            return selected and count == 1
        elif field["kind"] == "combobox":
            if value not in field["options"]:
                raise HTTPException(
                    409, "Custom dropdown choice changed; analyze again"
                )
            from backend.app.browser.dropdowns import open_reviewed

            element = await open_reviewed(self, field)
            options = self.page.locator(f'[data-aa-options="{field["key"]}"]')
            choice = options.get_by_role("option", name=value, exact=True)
            if await options.count() != 1 or await choice.count() != 1:
                raise HTTPException(409, "Custom dropdown changed; take over manually")
            await choice.click(timeout=5000)
            return await element.evaluate(
                "(e, expected) => e.getAttribute('aria-expanded') === 'false' && (e.tagName === 'INPUT' ? e.value === expected && e.validity.valid : e.innerText.trim() === expected)",
                value,
            )
        else:
            await element.fill(value)
        # DOM validity is evidence of completeness, never proof of submission.
        return await element.evaluate("(e) => e.validity ? e.validity.valid : false")

    async def submit_mock(self, adapter, attempt_id, payload_digest):
        if self.cancelled:
            raise HTTPException(
                409, "Browser dispatch was cancelled; inspect its receipt"
            )
        # The route allows only one exact mock POST and its exact receipt navigation.
        self.submission = {
            "id": attempt_id,
            "digest": payload_digest,
            "action": adapter.action,
            "receipt_url": adapter.base + "/mock/receipt/" + str(attempt_id),
            "used": False,
        }
        try:
            await self.page.evaluate(
                """data => {
              const f = document.forms[0];
              f.elements.namedItem('_aa_attempt_id').value = data.id;
              f.elements.namedItem('_aa_payload_digest').value = data.digest;
              window.__aaManual = true;
            }""",
                {"id": str(attempt_id), "digest": payload_digest},
            )
            await self.page.locator(
                'form[data-aa-mock-fixture] button[type="submit"]'
            ).click(timeout=5000)
            await self.page.wait_for_url(self.submission["receipt_url"], timeout=10000)
        finally:
            self.submission = None
            if not self.page.is_closed():
                await self.page.evaluate("window.__aaManual = false")

    async def close(self):
        self.cancelled = True
        await self.resources.close()


class LocalBrowser:
    def __init__(self):
        self.sessions = {}
        self.opening = set()
        self.opening_resources = {}
        self.locks = {}
        from backend.app.browser.operations import BrowserOperations

        self.operations = BrowserOperations(self.lock)

    def lock(self, packet_id):
        return self.locks.setdefault(str(packet_id), asyncio.Lock())

    async def open(self, packet_id, url, settings):
        target, addresses = await validate_destination(
            url, settings, return_addresses=True
        )
        asset_origins = [
            value for value in policy(settings)["origins"] if value != target
        ]
        resolved_assets = await asyncio.gather(
            *[
                validate_destination(
                    value,
                    settings,
                    return_addresses=True,
                    allowed_origins=asset_origins,
                )
                for value in asset_origins
            ]
        )
        self.operations.checkpoint(packet_id)
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
        resources = BrowserResources()
        resources.assets = PublicAssets(
            dict(resolved_assets), testing=settings.ENVIRONMENT == "testing"
        )
        self.opening_resources[key] = resources
        playwright = context = None
        try:
            playwright = await async_playwright().start()
            resources.playwright = playwright
            resources.checkpoint()
            context = await playwright.chromium.launch_persistent_context(
                str(directory),
                # Pin the approved hostname to its validated address for the entire session.
                # TLS still verifies the original hostname; no proxy/DNS rebind can reach LAN.
                args=[
                    f"--host-resolver-rules=MAP {urlsplit(url).hostname} {addresses[0]}",
                    "--dns-over-https-mode=off",
                    "--no-proxy-server",
                ],
                **launch_options(settings.BROWSER_CHANNEL),
                headless=settings.BROWSER_HEADLESS,
                accept_downloads=False,
                service_workers="block",
                timeout=30000,
            )
            resources.context = context
            resources.checkpoint()
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
            session = BrowserSession(context, page, target, url, playwright, resources)
            await context.expose_binding("__aaOwnerMode", session.owner_mode)
            page.on("framenavigated", session.navigated)
            await context.route("**/*", session.route)
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=15000
            )
            resources.checkpoint()
            session.navigating = False
            session.assisted_document_epoch = session.document_epoch
            if response is None or response.status >= 400:
                raise HTTPException(409, "Destination unavailable; take over manually")
            self.sessions[key] = session
            return session
        except BaseException:
            await resources.close()
            raise
        finally:
            self.opening.discard(key)
            self.opening_resources.pop(key, None)

    async def close(self, packet_id):
        session = self.sessions.pop(str(packet_id), None)
        if session:
            await session.close()
        resources = self.opening_resources.get(str(packet_id))
        if resources:
            await resources.close()


browser = LocalBrowser()
