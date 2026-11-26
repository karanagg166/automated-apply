"""Phase 9B worker scheduling: P0/P1 priority lane, wake-ups, per-portal cooldowns, global apply gap,
priority decay, fresh sweeps and the Phase 9 startup refusal (MemoryStore + fake adapters)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from backend.app.browser_v2 import service as service_pkg
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import DiscoveryMeta, MemoryStore
from backend.app.browser_v2.worker import FRESH_SWEEP_LIMIT, Worker, run_worker
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


class OrderedAdapter(FakeAdapter):
    """Records live applies in one list shared by every portal (cross-portal ordering)."""

    def __init__(self, platform, jobs, order, sleeps=None, on_apply=None, **kw):
        super().__init__(platform, jobs, **kw)
        self.order, self.sleeps, self.on_apply = order, sleeps, on_apply
        self.discover_calls: list[dict] = []

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        self.discover_calls.append({"query": query, "limit": limit, "age": job_age_days})
        return await super().discover_jobs(page, query=query, limit=limit, job_age_days=job_age_days)

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        result = await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                         hitl_answers=hitl_answers)
        if not dry_run:
            self.order.append((detail.listing.external_job_id, sum(self.sleeps.calls) if self.sleeps else 0))
            if self.on_apply is not None:
                await self.on_apply(detail.listing.external_job_id)
        return result


def make_worker(store, adapters, *, clock=None, sleeps=None):
    service = BrowserService(FakeManager(), store, adapters=adapters)  # type: ignore[arg-type]
    sleeps = sleeps if sleeps is not None else Sleeps()
    worker = Worker(service, clock=clock or (lambda: NOON_IST), sleeper=sleeps, idle_poll_sec=5,
                    cycle_interval_sec=600)
    return worker, sleeps


@pytest.fixture(autouse=True)
def no_dry_env(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)


async def queue_p0(store, platform, i):
    return await store.upsert_discovered(job(i, platform, company=f"Urgent {platform} {i}"),
                                         DiscoveryMeta(priority=0, priority_reason="owner_requested"))


# --- priority lane ---------------------------------------------------------------------------------
async def test_p0_on_another_portal_jumps_the_queue_at_cycle_start():
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    order: list = []
    naukri = OrderedAdapter("naukri", [job(1), job(2)], order)
    instahyre = OrderedAdapter("instahyre", [], order)
    await queue_p0(store, "instahyre", 7)
    worker, _ = make_worker(store, {"naukri": naukri, "instahyre": instahyre})
    report = await worker.cycle()
    assert next(j for j, _ in order) == "instahyre-7"  # before naukri's rotation turn
    by = {p.platform: p for p in report.portals}
    assert by["instahyre"].priority == 1 and by["naukri"].applied == 2
    assert [p.platform for p in report.portals] == [r.platform for r in await store.list_rules()]


async def test_p0_discovered_mid_turn_runs_after_the_current_job_not_after_the_turn():
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    order: list = []
    sleeps = Sleeps()

    async def watcher_finds_p0(job_id):
        if job_id == "naukri-1":
            await queue_p0(store, "instahyre", 9)

    naukri = OrderedAdapter("naukri", [job(1), job(2)], order, sleeps, on_apply=watcher_finds_p0)
    instahyre = OrderedAdapter("instahyre", [], order, sleeps)
    worker, _ = make_worker(store, {"naukri": naukri, "instahyre": instahyre}, sleeps=sleeps)
    await worker.cycle()
    assert [j for j, _ in order] == ["naukri-1", "instahyre-9", "naukri-2"]
    # The P0 ran as soon as the 10-20 s global gap allowed, long before naukri's 45-150 s cooldown.
    (_, t1), (_, t_p0), (_, t2) = order
    assert 10 <= t_p0 - t1 <= 20 + 5 and t2 - t1 >= 45


async def test_priority_lane_is_bounded_per_drain():
    store = live_store({"instahyre": rules("instahyre", min_delay_sec=5, max_delay_sec=5)})
    for i in range(1, 9):
        await queue_p0(store, "instahyre", i)
    adapter = OrderedAdapter("instahyre", [], [])
    worker, _ = make_worker(store, {"instahyre": adapter}, clock=Clock())
    worker.ctx = await worker.load_context(await store.get_worker_control(), run_once=False)
    assert await worker.drain_priority() <= 5


async def test_lane_respects_portal_gates():
    store = live_store({"naukri": rules(auto_apply_enabled=False), "instahyre": rules("instahyre", enabled=False)})
    await queue_p0(store, "naukri", 1)
    await queue_p0(store, "instahyre", 1)
    naukri, instahyre = FakeAdapter("naukri", []), FakeAdapter("instahyre", [])
    worker, _ = make_worker(store, {"naukri": naukri, "instahyre": instahyre})
    worker.ctx = await worker.load_context(await store.get_worker_control(), run_once=False)
    assert await worker.drain_priority() == 0  # inspect-only portal + disabled portal: no live lane
    assert naukri.inspected == [] and instahyre.inspected == []


# --- wake-ups --------------------------------------------------------------------------------------
async def test_wake_cuts_a_long_sleep_short_with_a_fake_sleeper():
    store = live_store({"naukri": rules()})
    worker, sleeps = make_worker(store, {"naukri": FakeAdapter("naukri", [])})

    async def wake_on_first_chunk(seconds):
        sleeps.calls.append(seconds)
        worker.wake("watcher:greenhouse")

    worker._sleep = wake_on_first_chunk
    assert await worker.sleep(3600) is True  # True = continue
    assert sleeps.calls == [5] and not worker.wake_event.is_set()
    assert worker.wake_reasons[-1] == "watcher:greenhouse"


async def test_wake_cuts_a_real_asyncio_sleep_short():
    store = live_store({"naukri": rules()})
    service = BrowserService(FakeManager(), store, adapters={"naukri": FakeAdapter("naukri", [])})  # type: ignore
    worker = Worker(service, idle_poll_sec=3600)
    task = asyncio.create_task(worker.sleep(3600))
    await asyncio.sleep(0.05)
    worker.wake("telegram")
    assert await asyncio.wait_for(task, timeout=2) is True


async def test_control_tick_wakes_for_run_once_and_new_priority_rows():
    store = live_store({"naukri": rules()})
    worker, sleeps = make_worker(store, {"naukri": FakeAdapter("naukri", [])})
    worker.ctx = await worker.load_context(await store.get_worker_control(), run_once=False)
    assert await worker.sleep(30) is True and sum(sleeps.calls) == 30  # nothing to wake for
    await queue_p0(store, "naukri", 1)
    sleeps.calls.clear()
    assert await worker.sleep(3600) is True and sleeps.calls == []  # P0 from another process: woken
    sleeps.calls.clear()
    assert await worker.sleep(10) is True and sum(sleeps.calls) == 10  # same row never re-wakes
    await store.set_worker_control(run_once=True)
    sleeps.calls.clear()
    assert await worker.sleep(3600) is True and sleeps.calls == []
    assert "run_once" in worker.wake_reasons


async def test_wake_never_aborts_an_in_flight_job():
    store = live_store({"naukri": rules()})
    holder: dict = {}

    class WakingAdapter(FakeAdapter):
        async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
            holder["worker"].wake("mid-job")
            await asyncio.sleep(0)
            return await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                           hitl_answers=hitl_answers)

    adapter = WakingAdapter("naukri", [job(1)])
    worker, _ = make_worker(store, {"naukri": adapter})
    holder["worker"] = worker
    report = await worker.cycle()
    assert report.portals[0].applied == 1 and not report.interrupted
    assert store.records[("naukri", "naukri-1")].state is S.APPLIED
    assert worker.wake_event.is_set()  # the wake is left for the next between-jobs sleep


# --- cooldowns -------------------------------------------------------------------------------------
async def test_cooldown_replaces_the_blocking_sleep_and_global_gap_spaces_portals():
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    order: list = []
    sleeps = Sleeps()
    naukri = OrderedAdapter("naukri", [job(1)], order, sleeps)
    instahyre = OrderedAdapter("instahyre", [job(1, "instahyre", company="Other")], order, sleeps)
    worker, _ = make_worker(store, {"naukri": naukri, "instahyre": instahyre}, sleeps=sleeps)
    await worker.cycle()
    (_, t1), (_, t2) = order
    assert 10 <= t2 - t1 <= 20 + 5  # global minimum gap, not naukri's 45-150 s jitter
    assert sum(sleeps.calls) <= 25  # nothing slept on after the last apply
    assert set(worker.next_apply_at) == {"naukri", "instahyre"}


async def test_cooldown_past_the_next_cycle_drops_deferred_work():
    store = live_store({"naukri": rules(min_delay_sec=3000, max_delay_sec=3000)})
    adapter = FakeAdapter("naukri", [job(1), job(2)])
    worker, _ = make_worker(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].applied == 1 and report.portals[0].stopped_reason == "cooldown_past_cycle"
    assert worker.deferred == {}
    assert store.records[("naukri", "naukri-2")].state is S.DISCOVERED  # kept for the next cycle


# --- decay + fresh sweeps --------------------------------------------------------------------------
async def test_housekeeping_decays_priorities_every_ten_minutes():
    clock = Clock()
    store = live_store({"naukri": rules()})
    stale = await queue_p0(store, "naukri", 1)
    store.records[("naukri", "naukri-1")].created_at = NOON_IST - timedelta(hours=3)
    calls: list = []
    original = store.decay_priorities

    async def counting(now):
        calls.append(now)
        return await original(now)

    store.decay_priorities = counting
    worker, _ = make_worker(store, {"naukri": FakeAdapter("naukri", [])}, clock=clock)
    await worker.housekeeping()
    await worker.housekeeping()
    assert len(calls) == 1 and (await store.get_application(stale.id)).priority == 1
    clock.now += timedelta(minutes=11)
    await worker.housekeeping()
    assert len(calls) == 2 and {"priority_decayed": 1} in worker.housekeeping_log


async def sweep_worker(clock, *, jobs=None, budget=6):
    store = live_store({"naukri": rules()})
    adapter = OrderedAdapter("naukri", jobs if jobs is not None else [job(1)], [])
    worker, _ = make_worker(store, {"naukri": adapter}, clock=clock)
    worker.sweep_hourly_budget = budget
    worker.session_ok_at["naukri"] = clock.now
    ctx = await worker.load_context(await store.get_worker_control(), run_once=False)
    return store, adapter, worker, ctx


async def test_fresh_sweep_cadence_page_one_and_recorded():
    clock = Clock()
    store, adapter, worker, ctx = await sweep_worker(clock, jobs=[])
    assert await worker.maybe_sweep(ctx) == ["naukri"]
    assert adapter.discover_calls == [{"query": "Python Developer", "limit": FRESH_SWEEP_LIMIT, "age": 1}]
    assert store.rules["naukri"].last_fresh_sweep_at == NOON_IST
    assert await worker.maybe_sweep(ctx) == []  # not due again yet (20 min +- 20 %)
    clock.now += timedelta(minutes=15)
    worker.session_ok_at["naukri"] = clock.now
    assert await worker.maybe_sweep(ctx) == []
    clock.now += timedelta(minutes=10)  # 25 min > 24 min upper jitter bound
    worker.session_ok_at["naukri"] = clock.now
    assert await worker.maybe_sweep(ctx) == ["naukri"] and len(adapter.discover_calls) == 2


async def test_fresh_sweep_hourly_page_load_budget():
    clock = Clock()
    _store, adapter, worker, ctx = await sweep_worker(clock, jobs=[], budget=1)
    assert await worker.maybe_sweep(ctx) == ["naukri"]
    worker.sweep_due.clear()  # even when the cadence says "due", the budget holds
    clock.now += timedelta(minutes=30)
    worker.session_ok_at["naukri"] = clock.now
    assert await worker.maybe_sweep(ctx) == [] and len(adapter.discover_calls) == 1
    clock.now += timedelta(minutes=31)
    worker.session_ok_at["naukri"] = clock.now
    assert await worker.maybe_sweep(ctx) == ["naukri"]


async def test_fresh_sweep_waits_while_priority_jobs_are_queued_and_needs_a_trusted_session():
    clock = Clock()
    store, adapter, worker, ctx = await sweep_worker(clock, jobs=[])
    await queue_p0(store, "naukri", 5)
    assert await worker.maybe_sweep(ctx) == [] and adapter.discover_calls == []
    worker.session_ok_at.clear()
    worker.sweep_due.clear()
    assert worker.seconds_until_sweep(clock.now) is None  # no session evidence: no extra page loads


async def test_fresh_sweep_scores_new_rows_and_the_lane_applies_them():
    clock = Clock()
    store, adapter, worker, ctx = await sweep_worker(clock, jobs=[job(1)])
    await worker.maybe_sweep(ctx)
    first = store.records[("naukri", "naukri-1")]
    assert first.discovered_via == "sweep:naukri" and first.state is S.APPLIED  # P1 (1 day old) drained
    adapter.jobs = [job(2)]
    clock.now += timedelta(minutes=30)
    worker.session_ok_at["naukri"] = clock.now
    worker.next_apply_at.clear()
    worker.next_global_apply_at = None
    await worker.maybe_sweep(ctx)
    second = store.records[("naukri", "naukri-2")]
    assert second.priority == 0 and second.priority_reason == "new_on_watched_source"  # baseline exists


# --- startup ---------------------------------------------------------------------------------------
async def test_run_worker_refuses_to_start_without_the_phase9_migration(monkeypatch):
    class Unmigrated(MemoryStore):
        async def phase9_ready(self):
            return False

    store = Unmigrated(rules={"naukri": rules()})
    manager = FakeManager()
    service = BrowserService(manager, store, adapters={"naukri": FakeAdapter("naukri", [])})  # type: ignore

    async def fake_build(**_kw):
        return service, "postgres"

    monkeypatch.setattr(service_pkg, "build_service", fake_build)
    with pytest.raises(RuntimeError, match="phase9_migration_missing"):
        await run_worker(dry_run=False, once=False, telegram=False)
    assert store.worker.observed_state == "OFFLINE" and store.worker.last_error == "phase9_migration_missing"
    assert manager.closed == 1
