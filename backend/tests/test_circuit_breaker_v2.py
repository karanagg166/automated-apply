"""Phase 9B persisted per-portal circuit breaker (replaces the in-memory portal back-off)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.browser_v2.outcomes import OutcomeCode
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.worker import Worker, circuit_open_seconds, outcome_code
from backend.tests.test_browser_v2_worker import (
    NOON_IST,
    FakeAdapter,
    FakeManager,
    Sleeps,
    job,
    live_store,
    rules,
)


class Clock:
    def __init__(self):
        self.now = NOON_IST

    def __call__(self):
        return self.now


class Bus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic, payload):
        self.events.append((topic, dict(payload)))

    def opened(self, platform=None):
        return [p for t, p in self.events if t == "portal.circuit_open" and platform in (None, p["platform"])]


class BrokenAdapter(FakeAdapter):
    """Job pages time out (Playwright-style) while `broken` is set."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.broken = True

    async def inspect_job(self, page, listing):
        self.inspected.append(listing.external_job_id)
        if self.broken:
            raise TimeoutError("page.goto: Timeout 45000ms exceeded")
        self.inspected.pop()
        return await super().inspect_job(page, listing)


def build(adapters, store, clock):
    service = BrowserService(FakeManager(), store, adapters=adapters)  # type: ignore[arg-type]
    service.event_bus = Bus()
    worker = Worker(service, clock=clock, sleeper=Sleeps(), idle_poll_sec=5)
    return worker, service.event_bus


@pytest.fixture(autouse=True)
def no_dry_env(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)


def test_open_durations_and_outcome_classification():
    assert [circuit_open_seconds(level) // 60 for level in (1, 2, 3, 4, 10)] == [15, 30, 60, 60, 60]
    assert outcome_code({"state": "APPLIED", "reason": "confirmation_text"}) is OutcomeCode.APPLIED
    assert outcome_code({"state": "FAILED", "reason": "apply_control_missing"}) is OutcomeCode.DOM_CHANGED
    assert outcome_code({"refused": "never_replay"}) is None
    assert outcome_code({"state": "QUOTA_HIT_PENDING", "reason": "x", "quota_blocked": True}) is None


async def test_three_consecutive_job_errors_open_the_breaker_once_and_other_portals_continue():
    clock = Clock()
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    broken = BrokenAdapter("naukri", [job(i) for i in range(1, 6)])
    healthy = FakeAdapter("instahyre", [job(1, "instahyre", company="Healthy Co")])
    worker, bus = build({"naukri": broken, "instahyre": healthy}, store, clock)
    report = await worker.cycle()
    by = {p.platform: p for p in report.portals}
    assert by["naukri"].stopped_reason == "consecutive_errors" and broken.inspected == ["naukri-1", "naukri-2",
                                                                                        "naukri-3"]
    rules_row = store.rules["naukri"]
    assert (rules_row.circuit_failures, rules_row.circuit_level) == (3, 1)
    assert rules_row.circuit_open_until == NOON_IST + timedelta(minutes=15)
    assert rules_row.circuit_reason.startswith("INFRA_ERROR")
    assert len(bus.opened("naukri")) == 1 and bus.opened()[0]["open_minutes"] == 15
    assert by["instahyre"].applied == 1  # other portals are unaffected
    again = await worker.cycle()
    by = {p.platform: p for p in again.portals}
    assert (by["naukri"].skipped or "").startswith("circuit_open_until:") and len(broken.inspected) == 3
    assert len(bus.opened()) == 1  # one event per opening
    assert store.rules["instahyre"].circuit_level == 0


async def test_half_open_runs_exactly_one_trial_and_escalates_to_the_60_minute_cap():
    clock = Clock()
    store = live_store({"naukri": rules()})
    broken = BrokenAdapter("naukri", [job(i) for i in range(1, 6)])
    worker, bus = build({"naukri": broken}, store, clock)
    await worker.cycle()
    assert store.rules["naukri"].circuit_level == 1
    for level, minutes in ((2, 30), (3, 60), (4, 60)):
        clock.now = store.rules["naukri"].circuit_open_until + timedelta(seconds=1)
        before = len(broken.inspected)
        report = await worker.cycle()
        assert len(broken.inspected) == before + 1  # half-open: exactly one trial job
        # The trial ran (priority lane or rotation turn) and re-opened the breaker for the rest of the cycle.
        assert report.portals[0].stopped_reason == "circuit_open" or (
            report.portals[0].skipped or "").startswith("circuit_open_until:")
        assert store.rules["naukri"].circuit_level == level
        assert store.rules["naukri"].circuit_open_until == clock.now + timedelta(minutes=minutes)
    assert len(bus.opened()) == 4 and [e["level"] for e in bus.opened()] == [1, 2, 3, 4]


async def test_successful_trial_resets_failures_and_level_and_the_turn_continues():
    clock = Clock()
    store = live_store({"naukri": rules()})
    broken = BrokenAdapter("naukri", [job(i) for i in range(1, 6)])
    worker, bus = build({"naukri": broken}, store, clock)
    await worker.cycle()
    broken.broken = False
    clock.now = store.rules["naukri"].circuit_open_until + timedelta(seconds=1)
    report = await worker.cycle()
    row = store.rules["naukri"]
    assert (row.circuit_failures, row.circuit_level, row.circuit_open_until) == (0, 0, None)
    assert report.portals[0].applied >= 2 and len(bus.opened()) == 1
    assert store.records[("naukri", "naukri-1")].state is S.APPLIED


async def test_only_consecutive_breaker_outcomes_count_and_auth_required_is_ignored():
    clock = Clock()
    store = live_store({"naukri": rules()})
    worker, bus = build({"naukri": FakeAdapter("naukri", [])}, store, clock)
    worker.load_circuits(await store.list_rules())
    await worker.observe("naukri", OutcomeCode.DOM_CHANGED)
    await worker.observe("naukri", OutcomeCode.CAPTCHA_WALL)
    await worker.observe("naukri", OutcomeCode.AUTH_REQUIRED)  # neither trips nor resets
    assert store.rules["naukri"].circuit_failures == 2
    await worker.observe("naukri", OutcomeCode.FILTERED)  # a working page resets the streak
    assert store.rules["naukri"].circuit_failures == 0
    for _ in range(2):
        await worker.observe("naukri", OutcomeCode.INFRA_ERROR)
    assert worker.circuit_blocked_until("naukri", clock.now) is None and bus.opened() == []
    await worker.observe("naukri", OutcomeCode.INFRA_ERROR)
    assert worker.circuit_blocked_until("naukri", clock.now) == NOON_IST + timedelta(minutes=15)


async def test_persisted_breaker_survives_a_worker_restart():
    clock = Clock()
    store = live_store({"naukri": rules()})
    broken = BrokenAdapter("naukri", [job(i) for i in range(1, 6)])
    first, _ = build({"naukri": broken}, store, clock)
    await first.cycle()
    restarted, _ = build({"naukri": broken}, store, clock)  # new process: only the DB row survives
    report = await restarted.cycle()
    assert (report.portals[0].skipped or "").startswith("circuit_open_until:") and len(broken.inspected) == 3
