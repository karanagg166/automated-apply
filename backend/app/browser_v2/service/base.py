"""BrowserService core state: adapters, gray-zone scoring, sessions, events, discovery."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.app.browser_v2.adapters.base import JobListing, PortalAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter
from backend.app.browser_v2.manager import BraveBrowserManager
from backend.app.browser_v2.rules import (
    CandidatePreferences,
    FilterResult,
    PortalRules,
    title_gray_zone,
)
from backend.app.browser_v2.service.helpers import plain
from backend.app.browser_v2.store import Store

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime


class BrowserServiceBase:
    def __init__(self, manager: BraveBrowserManager, store: Store,
                 adapters: dict[str, PortalAdapter] | None = None, *, ai: AIRuntime | None = None) -> None:
        self.manager = manager
        self.store = store
        self.adapters: dict[str, PortalAdapter] = adapters or {"naukri": NaukriAdapter()}
        self.ai = ai
        self._configured = False
        self.mail_reader: Any = None  # Phase 6A: MailReadService (auto email-OTP, recruiter replies)
        self.env_profile: dict[str, str] = {}  # project .env fallbacks (e.g. CANDIDATE_RESUME_PATH)
        self.auto_login: Any = None  # Phase 6A: browser_v2.auth.AutoLogin (Keychain / Google chip)
        self.event_bus: Any = None  # Phase 6A: events_v2 bus (lifecycle events)
        if ai is not None:
            for adapter in self.adapters.values():
                if hasattr(adapter, "answerer"):
                    adapter.answerer = ai.answerer
                if hasattr(adapter, "composer") and getattr(ai, "intro", None) is not None:
                    adapter.composer = ai.intro
                    if hasattr(adapter, "filler"):
                        adapter.filler.composer = ai.intro

    async def configure_adapters(self, profile: dict[str, Any] | None = None) -> None:
        """Per-cycle owner preferences for adapters (e.g. Greenhouse/Lever board lists)."""
        if profile is None:
            profile, _ = await self.store.load_profile()
        for adapter in self.adapters.values():
            configure = getattr(adapter, "configure", None)
            if callable(configure):
                configure(profile)
        self._configured = True

    def gray_zone_possible(self, title: str | None, prefs: CandidatePreferences) -> bool:
        return self.ai is not None and self.ai.jd_scorer.available and title_gray_zone(title, prefs)

    async def gray_zone_verdict(self, verdict: FilterResult, *, title: str | None, company: str | None,
                                description: str | None, prefs: CandidatePreferences,
                                passes_without_title: FilterResult) -> FilterResult:
        """LLM tie-breaker for a job that passed every hard filter except an ambiguous title."""
        if self.ai is None or not title or not description or not passes_without_title.passed:
            return verdict
        decision = await self.ai.jd_scorer.score(title=title, company=company, description=description,
                                                 target_roles=prefs.target_roles)
        if decision is None:
            return FilterResult(verdict.decision, verdict.reasons + ("llm_jd_unavailable",))
        note = f"llm_jd_{'match' if decision.accepted else 'reject'}: {decision.score:.2f} via {decision.source}"
        if decision.accepted:
            return FilterResult(passes_without_title.decision, passes_without_title.reasons + (note,))
        return FilterResult(verdict.decision, verdict.reasons + (note,))

    def adapter(self, platform: str) -> PortalAdapter:
        try:
            return self.adapters[platform]
        except KeyError:
            raise ValueError(f"unsupported_portal:{platform}") from None

    async def check_portal_session(self, platform: str) -> dict[str, Any]:
        adapter = self.adapter(platform)
        shot = None
        async with self.manager.job() as page:
            result = await adapter.check_session(page)
            if result.status.value != "OK":  # Phase 8b: evidence for UNKNOWN / AUTH_REQUIRED
                shot = await self._session_screenshot(page, platform)
        await self.store.record_auth(platform, result.status.value)
        output = plain(result)
        if shot:
            output["screenshot"] = shot
        return output

    async def _session_screenshot(self, page: Any, platform: str) -> str | None:
        try:
            from backend.app.browser_v2.receipts import capture

            return await capture(page, platform, "session", f"session-{datetime.now(UTC):%H%M%S}")
        except Exception:  # noqa: BLE001 - diagnostics never change the outcome
            return None

    async def attempt_auto_login(self, platform: str) -> dict[str, Any]:
        """One bounded auto re-login (30-min cooldown per portal) before the AUTH HITL."""
        if self.auto_login is None:
            return {"ok": False, "method": "none", "reason": "auto_login_disabled", "hitl_kind": "AUTH"}
        adapter = self.adapter(platform)
        async with self.manager.job() as page:
            result = await self.auto_login.attempt(platform, page, adapter)
        if result.ok:
            await self.store.record_auth(platform, "OK")
        return dict(result.public())

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        try:
            await self.event_bus.publish(topic, payload)
        except Exception:  # noqa: BLE001, S110 - events are best effort
            pass

    async def discover_listings(self, platform: str, query: str, limit: int = 20,
                                rules: PortalRules | None = None, *, newest_first: bool = False) -> list[JobListing]:
        adapter = self.adapter(platform)
        rules = rules or await self.store.get_rules(platform)
        if not self._configured:
            await self.configure_adapters()
        extra: dict[str, Any] = {}
        if newest_first and "sort" in inspect.signature(adapter.discover_jobs).parameters:
            extra["sort"] = "newest"  # Phase 9B fresh sweeps: only adapters that support it
        async with self.manager.job() as page:
            return await adapter.discover_jobs(page, query=query, limit=limit,
                                               job_age_days=rules.max_job_age_days, **extra)

    async def discover_portal_jobs(self, platform: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        output = []
        for listing in await self.discover_listings(platform, query, limit):
            record = await self.store.upsert_discovered(listing)
            output.append(plain(listing) | {"state": record.state.value})
        return output

    async def inspect_job_form(self, platform: str, url: str) -> dict[str, Any]:
        adapter = self.adapter(platform)
        async with self.manager.job() as page:
            await page.goto(url, wait_until="domcontentloaded")
            return await adapter.extract_form(page)

    async def recycle_browser(self) -> dict[str, Any]:
        await self.manager.recycle()
        return {"recycled": True}
