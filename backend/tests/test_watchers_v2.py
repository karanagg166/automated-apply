"""Phase 9B fast-poll watchers: baseline/delta, 304, Retry-After, breaker, HiringCafe MCP, budgets (no network)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
from backend.app.browser_v2.adapters.public_sources import RemotiveAdapter
from backend.app.browser_v2.store import ApplicationRecord, MemoryStore, WatcherState
from backend.app.browser_v2.watchers import (
    HIRINGCAFE_BUDGET,
    REMOTIVE_BUDGET,
    HiringCafeParseError,
    WatcherHub,
    WatchSource,
    build_watcher_hub,
    employer_apply_link,
    fallback_score_listing,
    parse_search,
)
from backend.app.browser_v2.watchers.sources import fetch_remotive, greenhouse_fetcher

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
PREFS = {"target_roles": ["backend engineer"]}
GH = WatchSource("greenhouse:acme", "greenhouse", "greenhouse", 180, fetch=greenhouse_fetcher("acme", "Acme"))
REMOTIVE = WatchSource("remotive", "remotive", "remotive", 6 * 3600, fetch=fetch_remotive, budget=REMOTIVE_BUDGET)


def gh_job(job_id: int, title: str, posted: datetime) -> dict[str, Any]:
    return {"id": job_id, "title": title, "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{job_id}",
            "first_published": posted.isoformat(), "location": {"name": "Remote"}}


async def wstate(store: MemoryStore, source: str) -> WatcherState:
    state = await store.get_watcher_state(source)
    assert state is not None
    return state


async def row(store: MemoryStore, platform: str, job_id: str) -> ApplicationRecord:
    record = await store.get(platform, job_id)
    assert record is not None
    return record


class Harness:
    def __init__(self, handler: Any = None, *, enabled: tuple[str, ...] = ("greenhouse", "remotive", "hiringcafe"),
                 store: MemoryStore | None = None, mcp: Any = None) -> None:
        self.now = NOW
        self.store = store or MemoryStore()
        self.requests: list[httpx.Request] = []
        self.wakes: list[str] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.enabled = set(enabled)

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        async def prefs() -> dict[str, Any]:
            return PREFS

        async def rules() -> dict[str, Any]:
            return {p: SimpleNamespace(enabled=p in self.enabled) for p in ("greenhouse", "remotive", "hiringcafe")}

        async def publish(topic: str, payload: dict[str, Any]) -> None:
            self.events.append((topic, payload))

        async def sleeper(seconds: float) -> None:
            return None

        self.hub = WatcherHub(self.store, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record)),
                              prefs_provider=prefs, score_listing=fallback_score_listing, wake=self.wakes.append,
                              publish=publish, clock=lambda: self.now, sleeper=sleeper, rules_provider=rules,
                              mcp_call=mcp)


async def test_baseline_then_delta_marks_p0_wakes_and_publishes_then_304():
    jobs = [gh_job(1, "Backend Engineer", NOW - timedelta(days=1))]

    def handler(request: httpx.Request) -> httpx.Response:
        etag = f'"v{len(jobs)}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        assert request.url.host == "boards-api.greenhouse.io" and "content" not in request.url.params
        return httpx.Response(200, json={"jobs": jobs}, headers={"etag": etag})

    h = Harness(handler)
    first = await h.hub.poll_once(GH)
    assert first.status == "baseline" and h.wakes == [] and h.events == []
    assert await h.store.get("greenhouse", "1") is None  # the baseline never queues anything
    state = await wstate(h.store, "greenhouse:acme")
    assert state.seen_ids == ("1",) and state.baseline_at == NOW and state.etag == '"v1"'

    h.now = NOW + timedelta(minutes=3)
    jobs.extend([gh_job(2, "Senior Backend Engineer", h.now - timedelta(minutes=30)),
                 gh_job(3, "Sales Manager", h.now - timedelta(minutes=10))])
    second = await h.hub.poll_once(GH)
    assert (second.status, second.new, second.upserted, second.p0) == ("polled", 2, 1, 1)
    assert h.requests[-1].headers["if-none-match"] == '"v1"'
    record = await row(h.store, "greenhouse", "2")
    assert record.priority == 0 and record.priority_reason == "posted_within_2h"
    assert record.discovered_via == "watcher:greenhouse" and await h.store.get("greenhouse", "3") is None
    assert h.wakes == ["watcher:greenhouse"]
    (topic, payload), = h.events
    assert topic == "job.priority_discovered" and payload["external_job_id"] == "2" and payload["ats_supported"]

    h.now += timedelta(minutes=3)
    third = await h.hub.poll_once(GH)
    assert third.status == "not_modified" and len(h.events) == 1
    assert (await wstate(h.store, "greenhouse:acme")).last_status == 304


async def test_retry_after_is_respected_and_persisted():
    h = Harness(lambda request: httpx.Response(429, headers={"retry-after": "120"}))
    outcome = await h.hub.poll_once(GH)
    assert outcome.status == "error" and outcome.next_poll_at == NOW + timedelta(seconds=120)
    state = await wstate(h.store, "greenhouse:acme")
    assert state.open_until == NOW + timedelta(seconds=120) and state.failures == 1 and state.last_status == 429
    assert (await h.hub.poll_once(GH)).status == "circuit_open" and len(h.requests) == 1
    h.now += timedelta(seconds=121)
    await h.hub.poll_once(GH)
    assert len(h.requests) == 2


async def test_per_source_breaker_opens_15_then_30_minutes_and_resets_on_success():
    healthy = {"ok": False}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": []}) if healthy["ok"] else httpx.Response(500)

    h = Harness(handler)
    for _ in range(3):
        assert (await h.hub.poll_once(GH)).status == "error"
    state = await wstate(h.store, "greenhouse:acme")
    assert state.failures == 3 and state.open_until == NOW + timedelta(minutes=15)
    assert state.last_error == "HttpStatusError:500"
    assert (await h.hub.poll_once(GH)).status == "circuit_open" and len(h.requests) == 3
    h.now += timedelta(minutes=16)
    await h.hub.poll_once(GH)
    assert (await wstate(h.store, "greenhouse:acme")).open_until == h.now + timedelta(minutes=30)
    h.now += timedelta(minutes=31)
    healthy["ok"] = True
    assert (await h.hub.poll_once(GH)).status == "baseline"
    state = await wstate(h.store, "greenhouse:acme")
    assert state.failures == 0 and state.open_until is None and state.last_error is None


async def test_disabled_portal_is_never_polled():
    h = Harness(lambda request: httpx.Response(200, json={"jobs": []}), enabled=())
    assert (await h.hub.poll_once(GH)).status == "disabled"
    assert await h.hub.enabled_sources("greenhouse") == []
    stop = asyncio.Event()

    async def stop_on_sleep(seconds: float) -> None:
        stop.set()

    h.hub.sleeper = stop_on_sleep
    await h.hub.run_family("remotive", stop)
    assert h.requests == []


# --- HiringCafe ---------------------------------------------------------------------------------------------
HC = """## HiringCafe job results (showing 2 of 98 matches)

### [Backend Engineer](https://hiringcafe.com/job/backend-engineer-acme-abcd1234efgh?utm_source=claude&utm_medium=x)
**Acme & Co**
- **Location:** Bengaluru, Karnataka, India
- **Workplace:** Remote
- **Posted:** {posted}
- **Job ID:** abcd1234efgh

Builds APIs.

---

### [Backend Developer](https://hiringcafe.com/job/backend-developer-beta-zz99yy88xx77)
**Beta**
- **Workplace:** Hybrid
- **Posted:** not a date
- **Job ID:** zz99yy88xx77
"""
DETAILS = """# [Backend Engineer](https://hiringcafe.com/job/backend-engineer-acme-abcd1234efgh)
- **View & apply:** https://hiringcafe.com/job/backend-engineer-acme-abcd1234efgh
- **Apply:** https://job-boards.greenhouse.io/acme/jobs/7654321?gh_src=hc.
"""


def test_hiringcafe_markdown_parse_is_tolerant_but_fails_closed():
    jobs = parse_search(HC.format(posted="2026-11-27"))
    assert [(j.job_id, j.company, j.workplace) for j in jobs] == [
        ("abcd1234efgh", "Acme & Co", "Remote"), ("zz99yy88xx77", "Beta", "Hybrid")]
    assert jobs[0].url == "https://hiringcafe.com/job/backend-engineer-acme-abcd1234efgh"
    assert jobs[0].posted_at == datetime(2026, 11, 27, tzinfo=UTC) and jobs[1].posted_at is None
    assert parse_search("## HiringCafe job results (showing 0 of 0 matches)") == []
    with pytest.raises(HiringCafeParseError):
        parse_search(HC.format(posted="2026-11-27").replace("- **Job ID:** zz99yy88xx77", ""))
    with pytest.raises(HiringCafeParseError):
        parse_search("<html>rate limited</html>")
    with pytest.raises(HiringCafeParseError):
        parse_search("### [X](https://evil.example/job/abcd1234)\n- **Job ID:** abcd1234")
    assert employer_apply_link(DETAILS) == "https://job-boards.greenhouse.io/acme/jobs/7654321?gh_src=hc"
    assert employer_apply_link("- **View & apply:** https://hiringcafe.com/job/x") is None


class FakeMcp:
    def __init__(self, search: str = "## HiringCafe job results (showing 0 of 0 matches)") -> None:
        self.search = search
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, arguments: dict[str, Any]) -> str:
        self.calls.append((tool, arguments))
        return self.search if tool == "search_jobs" else DETAILS


async def test_hiringcafe_delta_hands_p0_greenhouse_links_to_the_greenhouse_row():
    mcp = FakeMcp("## HiringCafe job results (showing 1 of 1 matches)\n" + HC.split("---")[1])
    h = Harness(mcp=mcp)
    source = h.hub.sources_for("hiringcafe", PREFS)[0]
    assert source.key == "hiringcafe:backend-engineer" and source.query == "backend engineer"
    assert (await h.hub.poll_once(source)).status == "baseline"
    tool, args = mcp.calls[0]
    assert tool == "search_jobs" and args["posted_within_days"] == 1 and args["max_years_experience"] == 1
    assert args["search"] == "backend engineer" and args["limit"] == 25
    mcp.search = HC.format(posted="2026-11-27")
    outcome = await h.hub.poll_once(source)
    assert (outcome.status, outcome.new, outcome.p0) == ("polled", 1, 1)
    assert [c[0] for c in mcp.calls] == ["search_jobs", "search_jobs", "get_job_details"]
    record = await row(h.store, "greenhouse", "7654321")
    assert record.priority == 0 and record.priority_reason == "new_on_watched_source"
    assert record.job_url == "https://job-boards.greenhouse.io/acme/jobs/7654321"
    assert await h.store.get("hiringcafe", "abcd1234efgh") is None and h.wakes == ["watcher:hiringcafe"]


async def test_hiringcafe_hourly_budget_is_persisted():
    mcp = FakeMcp()
    h = Harness(mcp=mcp)
    source = h.hub.sources_for("hiringcafe", PREFS)[0]
    outcomes = [await h.hub.poll_once(source) for _ in range(13)]
    assert [o.status for o in outcomes].count("budget_exhausted") == 1 and len(mcp.calls) == 12
    budget = await wstate(h.store, HIRINGCAFE_BUDGET.source)
    assert budget.budget_used == 12 and budget.last_poll_at == NOW.replace(minute=0)
    restarted = Harness(mcp=mcp, store=h.store)
    assert (await restarted.hub.poll_once(source)).status == "budget_exhausted"
    restarted.now = NOW + timedelta(hours=1)
    assert (await restarted.hub.poll_once(source)).status != "budget_exhausted" and len(mcp.calls) == 13


async def test_remotive_daily_budget_lives_in_watcher_state_and_is_shared_with_the_adapter():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "remotive.com"
        return httpx.Response(200, json={"jobs": []})

    h = Harness(handler)
    outcomes = [await h.hub.poll_once(REMOTIVE) for _ in range(5)]
    assert [o.status for o in outcomes][-1] == "budget_exhausted" and len(h.requests) == 4
    assert (await wstate(h.store, "remotive:budget")).budget_used == 4
    adapter = RemotiveAdapter(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                              clock=lambda: NOW)
    adapter.use_store(h.store)
    assert await adapter.fetch("python", 10) == []  # cap already spent by the watcher: no request
    restarted = Harness(handler, store=h.store)
    assert (await restarted.hub.poll_once(REMOTIVE)).status == "budget_exhausted"
    restarted.now = NOW + timedelta(days=1)
    assert (await restarted.hub.poll_once(REMOTIVE)).status == "not_modified"  # same body hash
    assert len(restarted.requests) == 1


async def test_run_polls_one_source_then_waits_and_build_hub_wires_runtime_objects():
    store = MemoryStore()
    woke: list[str] = []
    worker = SimpleNamespace(wake=woke.append)
    hub = build_watcher_hub(store, worker=worker, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"jobs": []}))))
    assert hub.wake == woke.append and hub.score_listing is fallback_score_listing and not hub.owns_client
    stop = asyncio.Event()
    polled: list[str] = []

    async def poll_once(source: Any) -> Any:
        polled.append(source.key)
        return SimpleNamespace(next_poll_at=None)

    async def enabled_sources(family: str) -> list[WatchSource]:
        return [REMOTIVE]

    async def sleeper(seconds: float) -> None:
        assert 0 < seconds <= 60
        stop.set()

    hub.poll_once, hub.enabled_sources, hub.sleeper = poll_once, enabled_sources, sleeper  # type: ignore[method-assign]
    hub.families = ("remotive",)
    await asyncio.wait_for(hub.run(stop), 5)
    assert polled == ["remotive"]


async def test_feed_adapters_sort_newest_first_and_carry_posted_at():
    posted = [NOW - timedelta(days=3), NOW - timedelta(hours=1), NOW - timedelta(days=1)]
    payload = {"jobs": [gh_job(i + 1, "Backend Engineer", p) for i, p in enumerate(posted)]}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    adapter = GreenhouseAdapter(boards={"acme": "Acme"}, http_client=client, clock=lambda: NOW)
    listings = await adapter.discover_jobs(None, query="backend engineer", limit=2)
    assert [item.external_job_id for item in listings] == ["2", "3"]
    assert listings[0].posted_at == posted[1] and listings[0].posted_at.tzinfo is not None
