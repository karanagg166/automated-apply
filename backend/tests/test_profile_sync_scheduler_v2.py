"""Phase 9D ProfileSyncScheduler: interval, on-demand queue, profile.updated debounce, P0/P1 block."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.browser_v2.profile_sync.models import PROFILE_UPDATED_EVENT, SyncReport
from backend.app.browser_v2.profile_sync.runs import MemoryProfileSyncRuns
from backend.app.browser_v2.profile_sync.scheduler import (
    ProfileSyncRequester,
    ProfileSyncScheduler,
    build_profile_sync,
)

T0 = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Adapter:
    def __init__(self, calibrated: bool) -> None:
        self.calibrated = calibrated


class FakeService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.runs = MemoryProfileSyncRuns(clock)
        self.adapters = {"naukri": Adapter(True), "wellfound": Adapter(True), "instahyre": Adapter(False)}
        self.calls: list[tuple[str, bool, str]] = []

    async def sync(self, platform: str, *, dry_run: bool = True, trigger: str = "cli") -> SyncReport:
        self.calls.append((platform, dry_run, trigger))
        run_id = await self.runs.start(platform, trigger, dry_run)
        await self.runs.finish(run_id, "ok", {})
        return SyncReport(platform, dry_run, trigger, status="ok", run_id=run_id)


def scheduler(pending: list[bool] | None = None) -> tuple[ProfileSyncScheduler, FakeService, Clock]:
    clock = Clock()
    service = FakeService(clock)

    async def high_priority_pending() -> bool:
        return bool(pending and pending[0])

    sched = ProfileSyncScheduler(service, clock=clock, high_priority_pending=high_priority_pending)  # type: ignore[arg-type]
    return sched, service, clock


async def test_interval_runs_calibrated_portals_once_per_24h():
    sched, service, clock = scheduler()
    assert sched.portals == ("naukri", "wellfound")  # uncalibrated portals are not scheduled
    await sched.run_due()
    assert service.calls == [("naukri", False, "schedule"), ("wellfound", False, "schedule")]
    clock.now += timedelta(hours=23)
    assert await sched.run_due() == []
    clock.now += timedelta(hours=1, minutes=1)
    assert len(await sched.run_due()) == 2


async def test_on_demand_queue_replaces_and_ignores_unknown():
    sched, service, _ = scheduler()
    await sched.run_due()  # interval satisfied for both
    service.calls.clear()
    assert sched.request(["instahyre", "nope"], dry_run=True, trigger="telegram") == ["instahyre"]
    sched.request(["instahyre"], dry_run=False, trigger="dashboard")  # newer request wins
    assert [(r.platform, r.dry_run, r.trigger) for r in sched.queued] == [("instahyre", False, "dashboard")]
    await sched.run_due()
    assert service.calls == [("instahyre", False, "dashboard")] and sched.queued == []
    with pytest.raises(ValueError):
        sched.request(["naukri"], trigger="cron")


async def test_profile_updated_is_debounced_10_minutes():
    sched, service, clock = scheduler()
    await sched.run_due()
    service.calls.clear()
    await sched.on_event(PROFILE_UPDATED_EVENT, {})
    clock.now += timedelta(minutes=6)
    assert await sched.run_due() == []
    sched.note_profile_updated()  # a newer edit restarts the debounce
    clock.now += timedelta(minutes=9)
    assert await sched.run_due() == []
    clock.now += timedelta(minutes=1)
    await sched.run_due()
    assert service.calls == [("naukri", False, "profile_change"), ("wellfound", False, "profile_change")]
    clock.now += timedelta(minutes=30)
    assert await sched.run_due() == []  # consumed


async def test_pending_p0_p1_work_blocks_every_run():
    pending = [True]
    sched, service, _ = scheduler(pending)
    sched.request(["naukri"], dry_run=True)
    assert await sched.run_due() == [] and service.calls == []
    assert [r.platform for r in sched.queued] == ["naukri"]  # still queued
    pending[0] = False
    await sched.run_due()
    assert service.calls[0] == ("naukri", True, "telegram")


async def test_request_sync_protocol_returns_a_short_summary():
    from backend.app.browser_v2.store import MemoryStore

    sched = build_profile_sync(MemoryStore(), manager=None)
    assert isinstance(sched, ProfileSyncRequester)
    text = await sched.request_sync(["naukri", "bogus"], dry_run=True, trigger="telegram")
    assert text.startswith("Queued profile sync (dry-run) for naukri") and "bogus" in text
    assert "No profile sync queued" in await sched.request_sync(["bogus"], dry_run=True, trigger="telegram")
    assert sched.portals == ()  # every shipped adapter is uncalibrated: nothing on the interval
