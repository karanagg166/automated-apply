"""WatcherHub: one asyncio task per source family, round-robin, jittered, staggered.

Each family loop keeps a due-time per source (first polls spread evenly across the family
interval, later ones `interval * U(0.8, 1.2)` after the last poll, or the breaker /
Retry-After time), sleeps until the earliest one and polls exactly one source. All HTTP goes
through one shared `ConditionalHttp`, so a host never sees more than one request at a time.
The hub is not wired into the worker here: the orchestrator calls `build_watcher_hub(...)`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from backend.app.browser_v2.adapters.feed_clients.http import ConditionalHttp
from backend.app.browser_v2.adapters.feeds import USER_AGENT
from backend.app.browser_v2.adapters.we_work_remotely import feeds as wwr_feeds
from backend.app.browser_v2.watchers.hiringcafe import fastmcp_call
from backend.app.browser_v2.watchers.models import (
    FAMILIES,
    FAMILY_INTERVALS,
    FAMILY_STAGGER_SEC,
    HIRINGCAFE_BUDGET,
    IDLE_RECHECK_SEC,
    JITTER,
    MAX_SLEEP_SEC,
    REMOTIVE_BUDGET,
    Clock,
    McpCall,
    PrefsProvider,
    Publish,
    RulesProvider,
    ScoreListing,
    Sleeper,
    Wake,
    WatchSource,
    fallback_score_listing,
    role_slug,
    target_roles,
)
from backend.app.browser_v2.watchers.poller import WatcherPoller
from backend.app.browser_v2.watchers.sources import (
    ashby_fetcher,
    configured_boards,
    fetch_arbeitnow,
    fetch_hacker_news,
    fetch_remotive,
    greenhouse_fetcher,
    himalayas_fetcher,
    lever_fetcher,
    wwr_fetcher,
)

logger = logging.getLogger(__name__)
PER_HOST_MIN_INTERVAL_SEC = 2.0
BOARD_FAMILIES = {"greenhouse": ("GREENHOUSE_BOARDS", "greenhouse_boards", greenhouse_fetcher),
                  "lever": ("LEVER_BOARDS", "lever_boards", lever_fetcher),
                  "ashby": ("ASHBY_BOARDS", "ashby_boards", ashby_fetcher)}


class WatcherHub(WatcherPoller):
    def __init__(self, store: Any, *, http_client: httpx.AsyncClient, prefs_provider: PrefsProvider,
                 score_listing: ScoreListing, wake: Wake, publish: Publish, clock: Clock | None = None,
                 sleeper: Sleeper | None = None, rules_provider: RulesProvider | None = None,
                 mcp_call: McpCall | None = None, rng: random.Random | None = None,
                 families: tuple[str, ...] = FAMILIES) -> None:
        self.store = store
        self.http_client = http_client
        self.prefs_provider = prefs_provider
        self.score_listing = score_listing
        self.wake = wake
        self.publish = publish
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper or asyncio.sleep
        self.rules_provider = rules_provider or self._store_rules
        self.mcp_call = mcp_call or fastmcp_call
        self.rng = rng or random.Random()
        self.families = tuple(f for f in families if f in FAMILY_INTERVALS)
        self.http = ConditionalHttp(http_client, min_interval=PER_HOST_MIN_INTERVAL_SEC, sleep=self.sleeper)
        self.owns_client = False

    async def _store_rules(self) -> Mapping[str, Any]:
        return {rule.platform: rule for rule in await self.store.list_rules()}

    # --- source catalogue -----------------------------------------------------------------------
    def sources_for(self, family: str, prefs: Mapping[str, Any]) -> list[WatchSource]:
        interval = FAMILY_INTERVALS[family]
        if family in BOARD_FAMILIES:
            setting, preference, factory = BOARD_FAMILIES[family]
            return [WatchSource(f"{family}:{board}", family, family, interval, fetch=factory(board, company))
                    for board, company in configured_boards(setting, preference, prefs).items()]
        if family == "himalayas":
            return [WatchSource(f"himalayas:{role_slug(role)}", family, family, interval,
                                fetch=himalayas_fetcher(role), query=role) for role in target_roles(prefs)]
        if family == "hiringcafe":
            return [WatchSource(f"hiringcafe:{role_slug(role)}", family, family, interval, kind="hiringcafe",
                                query=role, budget=HIRINGCAFE_BUDGET) for role in target_roles(prefs)]
        if family == "we_work_remotely":
            return [WatchSource(f"we_work_remotely:{role_slug(url.rsplit('/', 1)[-1].removesuffix('.rss'))}",
                                family, family, interval, fetch=wwr_fetcher(url)) for url in wwr_feeds()]
        single = {"remotive": (fetch_remotive, REMOTIVE_BUDGET), "arbeitnow": (fetch_arbeitnow, None),
                  "hacker_news": (fetch_hacker_news, None)}
        fetch, budget = single[family]
        return [WatchSource(family, family, family, interval, fetch=fetch, budget=budget)]

    async def enabled_sources(self, family: str) -> list[WatchSource]:
        try:
            if not await self.enabled(family):
                return []
            return self.sources_for(family, await self.prefs())
        except Exception as exc:  # noqa: BLE001 - rules/profile unreadable: idle, retry later
            logger.info("watcher %s source list failed: %s", family, type(exc).__name__)
            return []

    async def find_source(self, key: str) -> WatchSource | None:
        family = key.split(":", 1)[0]
        if family not in FAMILY_INTERVALS:
            return None
        return next((s for s in self.sources_for(family, await self.prefs()) if s.key == key), None)

    # --- scheduling -------------------------------------------------------------------------------
    def jittered(self, interval: float) -> float:
        return interval * self.rng.uniform(1 - JITTER, 1 + JITTER)

    async def _pause(self, seconds: float, stop: asyncio.Event) -> None:
        if seconds > 0 and not stop.is_set():
            await self.sleeper(min(seconds, MAX_SLEEP_SEC))

    async def run_family(self, family: str, stop: asyncio.Event, *, offset: float = 0.0) -> None:
        await self._pause(offset, stop)
        due: dict[str, datetime] = {}
        while not stop.is_set():
            sources = {s.key: s for s in await self.enabled_sources(family)}
            if not sources:
                due.clear()
                await self._pause(IDLE_RECHECK_SEC, stop)
                continue
            now = self.clock()
            interval = FAMILY_INTERVALS[family]
            for key in [k for k in due if k not in sources]:
                del due[key]
            fresh = [k for k in sources if k not in due]
            for index, key in enumerate(fresh):  # spread new sources across one interval
                due[key] = now + timedelta(seconds=interval * index / max(len(fresh), 1))
            key = min(due, key=lambda k: due[k])
            wait = (due[key] - now).total_seconds()
            if wait > 0:
                await self._pause(wait, stop)
                continue
            outcome = await self.poll_once(sources[key])
            after = self.clock()
            due[key] = after + timedelta(seconds=self.jittered(interval))
            if outcome.next_poll_at is not None and outcome.next_poll_at > due[key]:
                due[key] = outcome.next_poll_at

    async def run(self, stop_event: asyncio.Event) -> None:
        tasks = [asyncio.create_task(self._guarded(family, stop_event, index * FAMILY_STAGGER_SEC),
                                     name=f"watcher:{family}") for index, family in enumerate(self.families)]
        try:
            await stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.aclose()

    async def _guarded(self, family: str, stop: asyncio.Event, offset: float) -> None:
        while not stop.is_set():
            try:
                await self.run_family(family, stop, offset=offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one family's bug never stops the others
                logger.warning("watcher family %s crashed: %s", family, type(exc).__name__)
                await self._pause(IDLE_RECHECK_SEC, stop)
            offset = 0.0

    async def aclose(self) -> None:
        if self.owns_client:
            with contextlib.suppress(Exception):
                await self.http_client.aclose()


async def _profile_prefs(store: Any) -> Mapping[str, Any]:
    profile, _ = await store.load_profile()
    prefs = (profile or {}).get("preferences") if isinstance(profile, Mapping) else None
    return prefs if isinstance(prefs, Mapping) else {}


def build_watcher_hub(store: Any, *, service: Any = None, worker: Any = None, bus: Any = None,
                      http_client: httpx.AsyncClient | None = None, **overrides: Any) -> WatcherHub:
    """Hub wired from the runtime objects: `service.score_listing`, `worker.wake`, `bus.publish`.

    Any constructor argument can be overridden by keyword (tests, CLI)."""
    score = overrides.pop("score_listing", None) or getattr(service, "score_listing", None) \
        or fallback_score_listing

    def no_wake(reason: str) -> None:
        return None

    async def no_publish(topic: str, payload: dict[str, Any]) -> None:
        return None

    wake = overrides.pop("wake", None) or getattr(worker, "wake", None) or no_wake
    publish = overrides.pop("publish", None) or getattr(bus, "publish", None) or no_publish
    prefs = overrides.pop("prefs_provider", None) or (lambda: _profile_prefs(store))
    client = http_client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                              headers={"user-agent": USER_AGENT})
    hub = WatcherHub(store, http_client=client, prefs_provider=prefs, score_listing=score, wake=wake,
                     publish=publish, **overrides)
    hub.owns_client = http_client is None
    return hub
