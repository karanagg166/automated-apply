"""In-process browser tools shared by the 24/7 loop, the CLI and FastMCP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.adapters.base import JobListing, PortalAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter, external_job_id
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.manager import BraveBrowserManager
from backend.app.browser_v2.quota import contact_hints
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    CandidatePreferences,
    Decision,
    FilterResult,
    PortalRules,
    evaluate_pipeline,
    format_reason,
    is_title_mismatch_only,
    title_gray_zone,
)
from backend.app.browser_v2.state import (
    NEVER_REPLAY,
    TRANSITIONS,
    ApplicationState,
    ReplayRefused,
    guard_apply,
)
from backend.app.browser_v2.store import ApplicationRecord, Store

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime

S = ApplicationState
# A duplicate in any of these states means the role was (or is being) applied to elsewhere.
DUPLICATE_BLOCKING = NEVER_REPLAY | {S.APPLYING, S.WAITING_FOR_USER}


def plain(value: Any) -> Any:
    """JSON-friendly copy of adapter dataclasses/enums."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    return value


def day_start(rules: PortalRules, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(rules.timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def quota_counts(store: Store, rules: PortalRules, now: datetime | None = None) -> dict[str, Any]:
    """Live APPLIED counts for the portal's local day and the last rolling hour."""
    now = now or datetime.now(UTC)
    start = day_start(rules, now)
    today = await store.applied_since(rules.platform, start)
    hour = await store.applied_since(rules.platform, now - timedelta(hours=1))
    portal_limit_today = bool(rules.portal_limit_hit_at and rules.portal_limit_hit_at >= start)
    return {"applied_today": today, "applied_this_hour": hour,
            "daily_limit_hit": today >= rules.max_applies_per_day,
            "hourly_limit_hit": hour >= rules.max_applies_per_hour,
            "portal_limit_hit_today": portal_limit_today}


def can_move(record: ApplicationRecord, target: ApplicationState) -> bool:
    return record.state == target or target in TRANSITIONS[record.state]


def default_adapters(*, otp_provider: Any = None) -> dict[str, PortalAdapter]:
    """All 10 Phase 6A adapters (each portal still runs only when enabled in portal_rules)."""
    from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
    from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter
    from backend.app.browser_v2.adapters.hiringcafe import HiringCafeAdapter
    from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
    from backend.app.browser_v2.adapters.internshala import InternshalaAdapter
    from backend.app.browser_v2.adapters.lever import LeverAdapter
    from backend.app.browser_v2.adapters.public_sources import (
        ArbeitnowAdapter,
        AshbyAdapter,
        HackerNewsAdapter,
        RemotiveAdapter,
        SmartRecruitersAdapter,
    )
    from backend.app.browser_v2.adapters.we_work_remotely import WeWorkRemotelyAdapter
    from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
    from backend.app.browser_v2.adapters.work_at_a_startup import WorkAtAStartupAdapter

    adapters: list[Any] = [
        NaukriAdapter(otp_provider=otp_provider), GreenhouseAdapter(), LeverAdapter(), HimalayasAdapter(),
        WeWorkRemotelyAdapter(), HiringCafeAdapter(), InstahyreAdapter(), InternshalaAdapter(), WellfoundAdapter(),
        WorkAtAStartupAdapter(), AshbyAdapter(), SmartRecruitersAdapter(), RemotiveAdapter(), ArbeitnowAdapter(),
        HackerNewsAdapter()]
    return {adapter.platform: adapter for adapter in adapters}


def job_id_from_url(platform: str, url: str) -> str | None:
    """Stable external_job_id for a pasted job URL (CLI/MCP test-apply)."""
    import re
    from urllib.parse import urlsplit

    from backend.app.browser_v2.adapters.common import InteractivePortalAdapter

    parts = urlsplit(url)
    if parts.scheme != "https":
        return None
    segments = [s for s in parts.path.split("/") if s]
    if platform == "naukri":
        return external_job_id(url)
    if platform == "greenhouse":
        if len(segments) >= 3 and segments[1] == "jobs" and segments[2].isdigit():
            return segments[2]
        # Live 2026-11-26: custom career sites (stripe.com/jobs/search?gh_jid=<id>) and the
        # hosted embed form (job-boards.greenhouse.io/embed/job_app?for=<board>&token=<id>).
        from urllib.parse import parse_qs

        query = parse_qs(parts.query)
        candidate = (query.get("gh_jid") or (query.get("token") if "embed/job_app" in parts.path else None)
                     or [""])[0]
        return candidate if re.fullmatch(r"\d{1,20}", candidate) else None
    if platform == "lever":
        return segments[1] if len(segments) >= 2 and re.fullmatch(r"[0-9a-f-]{8,64}", segments[1]) else None
    if platform == "we_work_remotely":
        return segments[1] if len(segments) == 2 and segments[0] == "remote-jobs" else None
    if platform == "hacker_news":
        from urllib.parse import parse_qs as _qs

        item = (_qs(parts.query).get("id") or [""])[0]
        return item if parts.hostname == "news.ycombinator.com" and item.isdigit() else None
    if platform == "ashby":
        return segments[1] if parts.hostname == "jobs.ashbyhq.com" and len(segments) >= 2 and re.fullmatch(
            r"[0-9a-f-]{8,64}", segments[1]) else None
    if platform == "himalayas":
        from backend.app.browser_v2.adapters.himalayas import job_id

        return job_id(url, None, None) if "/jobs/" in parts.path else None
    adapters = default_adapters()
    adapter = adapters.get(platform)
    if isinstance(adapter, InteractivePortalAdapter):
        match = re.match(adapter.config.job_path, parts.path)
        return match.group(1) if match else None
    return None


class BrowserService:
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
        async with self.manager.job() as page:
            result = await adapter.check_session(page)
        await self.store.record_auth(platform, result.status.value)
        return plain(result)

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
                                rules: PortalRules | None = None) -> list[JobListing]:
        adapter = self.adapter(platform)
        rules = rules or await self.store.get_rules(platform)
        if not self._configured:
            await self.configure_adapters()
        async with self.manager.job() as page:
            return await adapter.discover_jobs(page, query=query, limit=limit,
                                               job_age_days=rules.max_job_age_days)

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

    async def quota_block(self, platform: str, rules: PortalRules | None = None,
                          now: datetime | None = None) -> str | None:
        rules = rules or await self.store.get_rules(platform)
        counts = await quota_counts(self.store, rules, now)
        if counts["daily_limit_hit"]:
            return "dashboard_daily_limit"
        if counts["portal_limit_hit_today"]:
            return "portal_daily_limit"
        if counts["hourly_limit_hit"]:
            return "dashboard_hourly_limit"
        return None

    async def duplicate_of(self, record: ApplicationRecord) -> ApplicationRecord | None:
        """Cross-portal dedup on normalized company::role (never apply to the same role twice)."""
        if not record.dedup_key:
            return None
        for other in await self.store.find_duplicates(record.dedup_key, platform=record.platform,
                                                      external_job_id=record.external_job_id):
            if other.state in DUPLICATE_BLOCKING:
                return other
        return None

    async def filter_out(self, record: ApplicationRecord, reason: str, *, record_filters: bool
                         ) -> ApplicationRecord:
        if record_filters and record.state != S.FILTERED_OUT and can_move(record, S.FILTERED_OUT):
            return await self.store.transition(record, S.FILTERED_OUT, reason)
        return record

    async def prefilter(self, listing: JobListing, rules: PortalRules, prefs: CandidatePreferences,
                        *, record_filters: bool) -> tuple[ApplicationRecord, FilterResult | None]:
        """Cheap search-card checks before opening the job page (no browser work)."""
        record = await self.store.upsert_discovered(listing)
        duplicate = await self.duplicate_of(record)
        if duplicate is not None:
            reason = f"duplicate_of: {duplicate.platform}:{duplicate.external_job_id} ({duplicate.state.value})"
            return await self.filter_out(record, reason, record_filters=record_filters), FilterResult(
                Decision.FILTERED, (reason,))
        verdict = evaluate_pipeline(
            age_days=listing.posted_age_days, applicants=listing.applicants or UNKNOWN_APPLICANTS,
            rules=rules, prefs=prefs, title=listing.title, company=listing.company,
            age_is_lower_bound=listing.age_is_lower_bound, require_description=False)
        # Unknown age/applicants on a card are re-checked on the job page; only hard fails stop here.
        if is_title_mismatch_only(verdict) and self.gray_zone_possible(listing.title, prefs):
            # Ambiguous title: open the JD (all other card-level filters must still pass).
            verdict = evaluate_pipeline(
                age_days=listing.posted_age_days, applicants=listing.applicants or UNKNOWN_APPLICANTS,
                rules=rules, prefs=replace(prefs, target_roles=()), title=listing.title,
                company=listing.company, age_is_lower_bound=listing.age_is_lower_bound,
                require_description=False)
        if verdict.decision is Decision.FILTERED:
            return await self.filter_out(record, format_reason(verdict),
                                         record_filters=record_filters), verdict
        return record, None

    # --- Phase 8: smart external ATS handoff --------------------------------------------------
    def handoff_target(self, platform: str, detail: Any) -> Any:
        """Supported Greenhouse/Lever posting behind another portal's external apply link."""
        from backend.app.browser_v2.adapters.common import (
            SUPPORTED_ATS,
            ats_handoff_target,
        )

        if platform in SUPPORTED_ATS or detail.apply_mode != "external":
            return None
        target = ats_handoff_target(detail.apply_url)
        return target if target is not None and target.platform in self.adapters else None

    async def hand_off(self, record: ApplicationRecord, detail: Any, target: Any, *,
                       record_filters: bool) -> dict[str, Any]:
        """Enqueue the posting for the greenhouse/lever adapter (DISCOVERED, deduped by the ATS job
        id) and close the source row as FILTERED_OUT `ats_handoff:<ats>:<id>` - never applied twice."""
        reason = f"ats_handoff:{target.platform}:{target.external_job_id}"
        result: dict[str, Any] = {"state": S.FILTERED_OUT.value, "reason": reason, "handoff": {
            "platform": target.platform, "external_job_id": target.external_job_id, "url": target.url,
            "board": target.board, "board_guessed": target.board_guessed}}
        if not record_filters:
            return result | {"handoff_recorded": False}
        existing = await self.store.get(target.platform, target.external_job_id)
        if existing is None:
            listing = detail.listing
            existing = await self.store.upsert_discovered(JobListing(
                platform=target.platform, external_job_id=target.external_job_id, url=target.url,
                title=listing.title, company=listing.company, posted_text=listing.posted_text,
                posted_age_days=detail.posted_age_days, age_is_lower_bound=listing.age_is_lower_bound,
                applicants=detail.applicants))
        result["handoff"]["state"] = existing.state.value
        await self.filter_out(record, reason, record_filters=True)
        await self.publish("job.ats_handoff", {"from": record.platform, "to": target.platform,
                                               "external_job_id": target.external_job_id})
        return result | {"handoff_recorded": True}

    async def apply_to_job(self, platform: str, url: str, *, dry_run: bool = True) -> dict[str, Any]:
        """Filter, guard and apply to one job URL (CLI/MCP)."""
        self.adapter(platform)
        job_id = job_id_from_url(platform, url)
        if not job_id:
            raise ValueError("unrecognized_job_url")
        listing = JobListing(platform=platform, external_job_id=job_id, url=url)
        return await self.process_job(listing, dry_run=dry_run)

    async def process_job(self, listing: JobListing, *, dry_run: bool,
                          rules: PortalRules | None = None,
                          profile: tuple[dict[str, Any], list[tuple[str, str]]] | None = None,
                          record_filters: bool | None = None, park_reason: str | None = None,
                          now: datetime | None = None) -> dict[str, Any]:
        """Inspect -> dedup -> filter pipeline -> (dry-run stop | reserve APPLYING -> apply).

        Live mode reserves APPLYING before clicking; any exception after the
        reservation becomes SUBMISSION_UNKNOWN (never replayed).
        Phase 5: `park_reason` (daily quota already hit) inspects and filters only, then
        parks a passing job as QUOTA_HIT_PENDING for the Gmail-draft + next-day retry path.
        """
        platform, job_id = listing.platform, listing.external_job_id
        record_filters = (not dry_run) if record_filters is None else record_filters
        adapter = self.adapter(platform)
        existing = await self.store.get(platform, job_id)
        try:
            guard_apply(existing.state if existing else None)
        except ReplayRefused as exc:
            return {"external_job_id": job_id, "refused": str(exc)}
        rules = rules or await self.store.get_rules(platform)
        if not dry_run:
            blocked = await self.quota_block(platform, rules, now)
            if blocked:
                return {"external_job_id": job_id, "state": S.QUOTA_HIT_PENDING.value, "reason": blocked,
                        "quota_blocked": True}
        loaded_profile, reviewed = profile if profile is not None else await self.store.load_profile()
        facts = apply_env_profile(CandidateFacts.from_profile(loaded_profile, reviewed), self.env_profile)
        prefs = CandidatePreferences.from_profile(loaded_profile)
        if self.ai is not None:
            self.ai.bind_profile(loaded_profile)
        hitl_id = None
        # Owner answers resolved via Telegram/dashboard HITL (one-time answers included).
        hitl_answers = await self.store.hitl_answers(existing.id) if existing is not None else {}
        async with self.manager.job() as page:
            detail = await adapter.inspect_job(page, listing)
            record = await self.store.upsert_discovered(detail.listing)
            try:
                guard_apply(record.state)
            except ReplayRefused as exc:
                return {"external_job_id": job_id, "refused": str(exc)}
            summary: dict[str, Any] = {
                "external_job_id": job_id, "application_id": record.id, "title": detail.listing.title,
                "company": detail.listing.company, "posted_age_days": detail.posted_age_days,
                "applicants": plain(detail.applicants), "apply_mode": detail.apply_mode,
                "salary": detail.salary_text, "dry_run": dry_run}
            duplicate = None if detail.already_applied else await self.duplicate_of(record)
            if duplicate is not None:
                reason = f"duplicate_of: {duplicate.platform}:{duplicate.external_job_id} ({duplicate.state.value})"
                await self.filter_out(record, reason, record_filters=record_filters)
                return summary | {"filter": Decision.FILTERED.value, "state": S.FILTERED_OUT.value,
                                  "reason": reason}
            verdict = evaluate_pipeline(
                age_days=detail.posted_age_days, applicants=detail.applicants, rules=rules, prefs=prefs,
                title=detail.listing.title, company=detail.listing.company,
                description=detail.description, salary_text=detail.salary_text,
                work_mode=detail.work_mode, age_is_lower_bound=detail.listing.age_is_lower_bound)
            if is_title_mismatch_only(verdict) and self.gray_zone_possible(detail.listing.title, prefs):
                verdict = await self.gray_zone_verdict(
                    verdict, title=detail.listing.title, company=detail.listing.company,
                    description=detail.description, prefs=prefs,
                    passes_without_title=evaluate_pipeline(
                        age_days=detail.posted_age_days, applicants=detail.applicants, rules=rules,
                        prefs=replace(prefs, target_roles=()), title=detail.listing.title,
                        company=detail.listing.company, description=detail.description,
                        salary_text=detail.salary_text, work_mode=detail.work_mode,
                        age_is_lower_bound=detail.listing.age_is_lower_bound))
            summary |= {"filter": verdict.decision.value, "filter_reasons": list(verdict.reasons)}
            if verdict.decision is not Decision.PASS and not detail.already_applied:
                reason = format_reason(verdict)
                await self.filter_out(record, reason, record_filters=record_filters)
                return summary | {"state": S.FILTERED_OUT.value, "reason": reason}
            handoff = self.handoff_target(platform, detail)
            if handoff is not None and not detail.already_applied:
                return summary | await self.hand_off(record, detail, handoff, record_filters=record_filters)
            hints = contact_hints(detail)
            if record_filters and record.state in {S.DISCOVERED, S.FAILED}:
                record = await self.store.transition(record, S.SCORED, "passed_filters",
                                                     payload={"reasons": list(verdict.reasons),
                                                              "contact_hints": hints})
            if detail.portal_limit:
                await self.store.record_portal_limit(platform)
                if record_filters and record.state == S.SCORED:
                    await self.store.transition(record, S.QUOTA_HIT_PENDING, "portal_daily_limit",
                                                payload={"limit_text": detail.portal_limit,
                                                         "contact_hints": hints})
                return summary | {"state": S.QUOTA_HIT_PENDING.value, "reason": "portal_daily_limit",
                                  "portal_limit": True}
            if park_reason is not None:
                if record_filters and record.state == S.SCORED:
                    await self.store.transition(record, S.QUOTA_HIT_PENDING, park_reason,
                                                payload={"contact_hints": hints})
                    return summary | {"state": S.QUOTA_HIT_PENDING.value, "reason": park_reason, "parked": True}
                return summary | {"state": record.state.value, "reason": "not_parked"}
            if dry_run:
                result = await adapter.apply_job(page, detail, facts, dry_run=True,
                                                 existing_state=record.state.value,
                                                 hitl_answers=hitl_answers)
                return summary | plain(result)
            record = await self.store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
            try:
                result = await adapter.apply_job(page, detail, facts, dry_run=False,
                                                 existing_state=S.DISCOVERED.value,
                                                 hitl_answers=hitl_answers)
            except Exception as exc:
                await self.store.transition(record, S.SUBMISSION_UNKNOWN,
                                            "exception_after_reservation:" + type(exc).__name__)
                raise
            record = await self.store.transition(
                record, result.state, result.reason, receipt=result.receipt,
                payload={"answers": list(result.answers), "clicked_apply": result.clicked_apply,
                         "screenshot": result.screenshot})
            if result.reason.startswith("portal_daily_limit"):
                await self.store.record_portal_limit(platform)
            if result.state == S.APPLIED:
                await self.publish("job.applied", {"platform": platform, "external_job_id": job_id,
                                                   "company": detail.listing.company, "title": detail.listing.title})
            elif result.state == S.QUOTA_HIT_PENDING:
                await self.publish("job.quota_hit", {"platform": platform, "external_job_id": job_id,
                                                     "reason": result.reason})
            if result.question is not None:
                hitl_id = await self.store.create_hitl(
                    record, platform, result.question.kind, result.question.prompt,
                    plain(result.question) | {"clicked_apply": result.clicked_apply,
                                              "title": detail.listing.title,
                                              "company": detail.listing.company,
                                              "url": detail.listing.url})
                await self.publish("hitl.opened", {"platform": platform, "kind": result.question.kind,
                                                   "external_job_id": job_id})
        await self.manager.maybe_recycle_between_jobs()
        return summary | plain(result) | {"hitl_request_id": hitl_id}


def env_profile_overrides(env: Mapping[str, str]) -> dict[str, str]:
    """Project-.env candidate fallbacks: only values the owner stored (never invented)."""
    path = (env.get("CANDIDATE_RESUME_PATH") or env.get("MAIL_DRAFT_RESUME_PATH") or "").strip()
    return {"resume_path": str(Path(path).expanduser())} if path else {}


def apply_env_profile(facts: CandidateFacts, overrides: Mapping[str, str]) -> CandidateFacts:
    """Fill the resume fallback from the project .env when the DB profile has no resume_files."""
    path = overrides.get("resume_path")
    if not path or not Path(path).is_file():
        return facts
    facts.identity.setdefault("resume_path", path)
    if not facts.resume_files:
        facts.resume_files = {"default": path}
    return facts


async def open_store(*, require_db: bool, env_file: str | None = None) -> tuple[Store, str]:
    """Postgres store; dry runs may fall back to memory before migration 004."""
    from backend.app.browser_v2.config import load_settings
    from backend.app.browser_v2.store import MemoryStore, PostgresStore

    try:
        return await PostgresStore.connect(load_settings(env_file)), "postgres"
    except Exception as exc:
        if require_db:
            raise RuntimeError(f"database_required_for_live_apply:{type(exc).__name__}:{exc}") from exc
        return MemoryStore(), f"memory ({type(exc).__name__}: {exc})"


async def build_ai(store: Store, env_file: str | None = None) -> AIRuntime | None:
    """Semantic cache + free LLM router on the store's connection (None if AI_V2_DISABLED)."""
    from backend.app.ai_v2.router import load_env
    from backend.app.ai_v2.runtime import AIRuntime, ai_disabled

    if ai_disabled():
        return None
    return await AIRuntime.for_store(store, env=load_env(env_file))


async def build_service(*, require_db: bool, env_file: str | None = None) -> tuple[BrowserService, str]:
    """Postgres-backed service; dry runs may fall back to memory before migration 004."""
    store, backend = await open_store(require_db=require_db, env_file=env_file)
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.auth import AutoLogin
    from backend.app.events_v2.bus import build_event_bus
    from backend.app.mail_v2.reader import MailEventStore, MailReadService

    env = load_env(env_file)
    connection = getattr(store, "connection", None)
    events = MailEventStore(connection if connection is not None and await MailEventStore.ready(connection) else None)
    reader = MailReadService.from_env(env, events=events)
    adapters = default_adapters(otp_provider=reader.fetch_recent_otp if reader.any_configured else None)
    service = BrowserService(BraveBrowserManager(), store, adapters, ai=await build_ai(store, env_file))
    service.mail_reader = reader
    profile, _ = await store.load_profile()
    owner_email = profile.get("email") if isinstance(profile.get("email"), str) else None
    if (env.get("AUTO_LOGIN_DISABLED") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        from backend.app.browser_v2.auth import ChainVault, EnvVault, KeychainVault

        service.auto_login = AutoLogin(ChainVault(EnvVault(env), KeychainVault()),
                                       mail_reader=reader if reader.any_configured else None, owner_email=owner_email)
    service.env_profile = env_profile_overrides(env)
    service.event_bus = build_event_bus(env, connection=connection)
    return service, backend
