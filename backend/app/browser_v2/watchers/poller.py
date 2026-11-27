"""One watcher poll: breaker / budget gates, conditional fetch, baseline-then-delta, score + upsert.

State per source lives in `watcher_state` (validators, seen ids, baseline, breaker, last error).
The first successful poll of a source only records its baseline; later polls treat unseen ids
as `newly_seen`. Nothing here raises into the scheduler: every failure is recorded instead.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from backend.app.browser_v2.adapters.common import (
    SUPPORTED_ATS,
    age_days_from,
    ats_handoff_target,
    classify_ats,
)
from backend.app.browser_v2.adapters.feed_clients.http import (
    ConditionalHttp,
    RateLimited,
    Validators,
)
from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.public_sources import StoreFetchBudget
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.rules import UNKNOWN_APPLICANTS
from backend.app.browser_v2.store.phase9_records import DiscoveryMeta, WatcherState
from backend.app.browser_v2.watchers.hiringcafe import (
    employer_apply_link,
    parse_search,
    search_arguments,
)
from backend.app.browser_v2.watchers.models import (
    BREAKER_OPEN,
    BREAKER_THRESHOLD,
    DEFAULT_RETRY_AFTER,
    HIRINGCAFE_BUDGET,
    BudgetSpec,
    Clock,
    Fetched,
    McpCall,
    PollOutcome,
    PrefsProvider,
    Publish,
    RulesProvider,
    ScoreListing,
    Wake,
    WatchSource,
    aware,
    passes_prefilter,
    target_roles,
)

logger = logging.getLogger(__name__)
Resolver = Callable[[JobListing, FeedJob], Awaitable[tuple[JobListing, str | None]]]


async def maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def to_listing(platform: str, job: FeedJob, now: datetime) -> JobListing:
    posted = aware(job.posted_at)
    return JobListing(platform=platform, external_job_id=job.external_job_id, url=job.url, title=job.title,
                      company=job.company, posted_text=posted.isoformat() if posted else None,
                      posted_age_days=age_days_from(posted, now), applicants=UNKNOWN_APPLICANTS, posted_at=posted)


def _error_text(exc: BaseException) -> str:
    status = getattr(exc, "status", None)
    return f"{type(exc).__name__}" + (f":{status}" if status is not None else "")


class WatcherPoller:
    store: Any
    http: ConditionalHttp
    http_client: Any
    prefs_provider: PrefsProvider
    rules_provider: RulesProvider
    score_listing: ScoreListing
    wake: Wake
    publish: Publish
    clock: Clock
    mcp_call: McpCall

    def budget(self, spec: BudgetSpec) -> StoreFetchBudget:
        return StoreFetchBudget(self.store, spec.source, spec.limit, window=spec.window, clock=self.clock)

    async def enabled(self, platform: str) -> bool:
        rules = await self.rules_provider()
        rule = rules.get(platform) if isinstance(rules, Mapping) else None
        return bool(rule is not None and getattr(rule, "enabled", False))

    async def prefs(self) -> Mapping[str, Any]:
        try:
            prefs = await self.prefs_provider()
        except Exception:  # noqa: BLE001 - no profile yet: no role filter, nothing configured
            return {}
        return prefs if isinstance(prefs, Mapping) else {}

    async def poll_once(self, source: WatchSource | str) -> PollOutcome:
        if isinstance(source, str):
            found = await self.find_source(source)
            if found is None:
                return PollOutcome(source, "unknown")
            source = found
        now = self.clock()
        state: WatcherState | None = None
        try:
            if not await self.enabled(source.platform):
                return PollOutcome(source.key, "disabled")
            state = await self.store.get_watcher_state(source.key) or WatcherState(source=source.key)
            if state.open_until is not None and state.open_until > now:
                return PollOutcome(source.key, "circuit_open", next_poll_at=state.open_until)
            prefs = await self.prefs()
            if source.kind == "hiringcafe":
                return await self._poll_hiringcafe(source, state, prefs, now)
            if source.budget is not None and not await self.budget(source.budget).acquire():
                return PollOutcome(source.key, "budget_exhausted")
            if source.fetch is None:
                return PollOutcome(source.key, "unknown")
            validators = Validators(state.etag, state.last_modified, state.body_hash)
            fetched = await source.fetch(self.http, self.http_client, validators)
            return await self._ingest(source, state, prefs, now, fetched)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded on the source's breaker, never raised
            return await self._failure(source, state, now, exc)

    async def find_source(self, key: str) -> WatchSource | None:
        raise NotImplementedError

    async def _failure(self, source: WatchSource, state: WatcherState | None, now: datetime,
                       exc: Exception) -> PollOutcome:
        if state is None:
            try:
                state = await self.store.get_watcher_state(source.key)
            except Exception:  # noqa: BLE001
                state = None
        state = state or WatcherState(source=source.key)
        failures = state.failures + 1
        open_until: datetime | None = None
        if isinstance(exc, RateLimited):
            wait = timedelta(seconds=exc.retry_after) if exc.retry_after is not None else DEFAULT_RETRY_AFTER
            open_until = now + wait
        if failures >= BREAKER_THRESHOLD:
            breaker = now + BREAKER_OPEN[min(failures - BREAKER_THRESHOLD, len(BREAKER_OPEN) - 1)]
            open_until = max(open_until, breaker) if open_until is not None else breaker
        error = _error_text(exc)
        logger.info("watcher %s poll failed (%s, failures=%s)", source.key, error, failures)
        try:
            await self.store.save_watcher_state(replace(
                state, failures=failures, open_until=open_until, last_error=error, last_poll_at=now,
                last_status=getattr(exc, "status", None)))
        except Exception as save_exc:  # noqa: BLE001 - the store being down must not kill the watcher
            logger.warning("watcher %s state save failed: %s", source.key, type(save_exc).__name__)
        return PollOutcome(source.key, "error", next_poll_at=open_until, error=error)

    async def _ingest(self, source: WatchSource, state: WatcherState, prefs: Mapping[str, Any], now: datetime,
                      fetched: Fetched, resolve: Resolver | None = None) -> PollOutcome:
        polled = replace(state, last_poll_at=now, last_status=fetched.status, failures=0, open_until=None,
                         last_error=None)
        if fetched.validators is not None:
            polled = replace(polled, etag=fetched.validators.etag, last_modified=fetched.validators.last_modified,
                             body_hash=fetched.validators.body_hash)
        if fetched.jobs is None:
            await self.store.save_watcher_state(polled)
            return PollOutcome(source.key, "not_modified")
        unique: dict[str, FeedJob] = {}
        for job in fetched.jobs:
            unique.setdefault(job.external_job_id, job)
        if state.baseline_at is None:  # first successful poll: remember what exists, mark nothing
            await self.store.save_watcher_state(replace(polled.with_seen(list(unique)), baseline_at=now))
            return PollOutcome(source.key, "baseline")
        seen = set(state.seen_ids)
        new_jobs = [job for job_id, job in unique.items() if job_id not in seen]
        outcome = PollOutcome(source.key, "polled", new=len(new_jobs))
        await self._discover(source, new_jobs, prefs, now, outcome, resolve)
        await self.store.save_watcher_state(polled.with_seen([job.external_job_id for job in new_jobs]))
        return outcome

    async def _discover(self, source: WatchSource, jobs: list[FeedJob], prefs: Mapping[str, Any], now: datetime,
                        outcome: PollOutcome, resolve: Resolver | None) -> None:
        roles = target_roles(prefs, limit=None)
        via = f"watcher:{source.platform}"
        for job in jobs:
            if not passes_prefilter(job, roles, now):
                continue
            listing = to_listing(source.platform, job, now)
            meta: DiscoveryMeta = await maybe_await(self.score_listing(listing, prefs, now=now, newly_seen=True,
                                                                       via=via))
            apply_url = job.apply_url
            if resolve is not None and meta.priority == 0:
                listing, apply_url = await resolve(listing, job)
            result = await self.store.upsert_discovered_meta(listing, meta)
            outcome.upserted += 1
            if not (result.inserted or result.promoted) or result.record.priority > 1:
                continue
            outcome.woke = True
            if result.record.priority == 0:
                outcome.p0 += 1
                await self._emit("job.priority_discovered", self._payload(source, listing, result.record, apply_url))
        if outcome.woke:
            try:
                await maybe_await(self.wake(f"watcher:{source.platform}"))
            except Exception as exc:  # noqa: BLE001 - a wake-up is a hint, never fatal
                logger.info("watcher wake failed: %s", type(exc).__name__)

    def _payload(self, source: WatchSource, listing: JobListing, record: Any, apply_url: str | None) -> dict[str, Any]:
        supported = listing.platform in SUPPORTED_ATS or classify_ats(apply_url) in SUPPORTED_ATS
        return {"application_id": record.id, "platform": listing.platform, "external_job_id": listing.external_job_id,
                "title": listing.title, "company": listing.company, "url": listing.url, "priority": record.priority,
                "reason": record.priority_reason, "posted_at": listing.posted_at.isoformat() if listing.posted_at
                else None, "source": source.key, "apply_url": apply_url or listing.url, "ats_supported": supported}

    async def _emit(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            await maybe_await(self.publish(topic, payload))
        except Exception as exc:  # noqa: BLE001 - e.g. a bus that does not know the topic yet
            logger.info("watcher publish %s failed: %s", topic, type(exc).__name__)

    # --- HiringCafe (MCP, hourly budget, details only for P0) -----------------------------------
    async def _poll_hiringcafe(self, source: WatchSource, state: WatcherState, prefs: Mapping[str, Any],
                               now: datetime) -> PollOutcome:
        budget = self.budget(source.budget or HIRINGCAFE_BUDGET)
        if not await budget.acquire():
            return PollOutcome(source.key, "budget_exhausted")
        markdown = await self.mcp_call("search_jobs", search_arguments(source.query or ""))
        jobs = [job.feed_job() for job in parse_search(markdown)]  # parse errors -> breaker (fail closed)

        async def resolve(listing: JobListing, job: FeedJob) -> tuple[JobListing, str | None]:
            if not await budget.acquire():
                return listing, None
            try:
                details = await self.mcp_call("get_job_details", {"job_id": job.external_job_id})
            except Exception as exc:  # noqa: BLE001 - keep the HiringCafe row; the worker inspects it later
                logger.info("hiringcafe details failed: %s", type(exc).__name__)
                return listing, None
            link = employer_apply_link(details)
            handoff = ats_handoff_target(link)
            if handoff is None:
                return listing, link
            return replace(listing, platform=handoff.platform, external_job_id=handoff.external_job_id,
                           url=handoff.url), link

        return await self._ingest(source, state, prefs, now, Fetched(200, None, jobs), resolve)
