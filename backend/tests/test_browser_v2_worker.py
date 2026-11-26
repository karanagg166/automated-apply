"""24/7 worker loop: quotas, auth isolation, non-blocking HITL, restart resume, never-replay."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    HitlQuestion,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.rules import PortalRules, parse_applicants
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.worker import Worker

NOON_IST = datetime(2026, 11, 26, 6, 30, tzinfo=UTC)


class FakeManager:
    def __init__(self):
        self.running = True
        self.recycle_checks = 0
        self.closed = 0

    @asynccontextmanager
    async def job(self):
        yield object()

    async def maybe_recycle_between_jobs(self, max_age_sec=10800):
        assert max_age_sec == 10800
        self.recycle_checks += 1
        return False

    async def close(self):
        self.closed += 1
        self.running = False


class FakeAdapter:
    """Scripted portal: listings, per-job detail overrides and per-job apply outcomes."""

    def __init__(self, platform, jobs, *, auth=AuthStatus.OK, outcomes=None, details=None):
        self.platform = platform
        self.jobs = jobs
        self.auth = auth
        self.outcomes = outcomes or {}
        self.details = details or {}
        self.applied: list[tuple[str, bool]] = []
        self.inspected: list[str] = []
        self.queries: list[str] = []

    async def check_session(self, page):
        return SessionCheck(self.auth)

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        self.queries.append(query)
        return list(self.jobs)

    async def inspect_job(self, page, listing):
        self.inspected.append(listing.external_job_id)
        base = next((j for j in self.jobs if j.external_job_id == listing.external_job_id), listing)
        extra = self.details.get(listing.external_job_id, {})
        return JobDetail(listing=base, applicants=extra.get("applicants", parse_applicants("20 applicants")),
                         posted_age_days=extra.get("age", 1), already_applied=False, apply_mode="direct",
                         description=extra.get("description", "python fastapi"),
                         portal_limit=extra.get("portal_limit"))

    async def extract_form(self, page):
        return {}

    async def detect_portal_limit(self, page):
        return None

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        job_id = detail.listing.external_job_id
        self.applied.append((job_id, dry_run))
        if dry_run:
            return ApplyResult(S.SCORED, "dry_run_stopped_before_apply_click", True)
        outcome = self.outcomes.get(job_id, "applied")
        if outcome == "question":
            return ApplyResult(S.WAITING_FOR_USER, "unknown_question", False, clicked_apply=True,
                               question=HitlQuestion(kind="QUESTION", prompt="Why us?"))
        return ApplyResult(S.APPLIED, "confirmation_text", False, clicked_apply=True,
                           receipt={"source": "fake"})


def job(i, platform="naukri", **kw):
    return JobListing(platform=platform, external_job_id=f"{platform}-{i}", url=f"https://example.com/{platform}/{i}",
                      title=kw.get("title", "Python Developer"), company=kw.get("company", f"Company {i}"),
                      posted_age_days=1, applicants=parse_applicants("20 applicants"))


def rules(platform="naukri", **kw):
    values = {"platform": platform, "enabled": True, "auto_apply_enabled": True, "min_delay_sec": 45,
                  "max_delay_sec": 150}
    values.update(kw)
    return PortalRules(**values)


class Sleeps:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


def build(store, adapters, *, force_dry_run=False):
    service = BrowserService(FakeManager(), store, adapters=adapters)  # type: ignore[arg-type]
    sleeps = Sleeps()
    worker = Worker(service, force_dry_run=force_dry_run, clock=lambda: NOON_IST, sleeper=sleeps,
                    idle_poll_sec=5, cycle_interval_sec=600)
    return worker, sleeps


def live_store(rule_map, **kw):
    return MemoryStore(rules=rule_map, profile={"preferences": {"target_roles": ["Python Developer"]}},
                       worker=WorkerControl(desired_state=WorkerState.RUNNING, dry_run=False), **kw)


@pytest.fixture(autouse=True)
def no_dry_env(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)


async def test_live_cycle_applies_with_jitter_and_recycle_checks():
    adapter = FakeAdapter("naukri", [job(1), job(2)])
    store = live_store({"naukri": rules()})
    worker, sleeps = build(store, {"naukri": adapter})
    report = await worker.cycle()
    portal = report.portals[0]
    assert portal.applied == 2 and [d for _, d in adapter.applied] == [False, False]
    assert store.records[("naukri", "naukri-1")].state is S.APPLIED
    # Phase 9B: the 45-150 s jitter is a per-portal cooldown, not a sleep after every apply. Job 2
    # waits out job 1's cooldown (sliced into 5 s pause-aware chunks) plus one 3-8 s inspection
    # pause; the cooldown after the last apply costs nothing in this cycle.
    assert 45 + 3 <= sum(sleeps.calls) <= 150 + 8 + 5
    assert all(s <= 5 for s in sleeps.calls)
    assert report.portals[0].deferred == 1 and "naukri" in worker.next_apply_at
    assert worker.service.manager.recycle_checks >= 2  # 3-hour recycle checked between jobs


async def test_daily_quota_marks_scored_jobs_quota_hit_pending_and_moves_on():
    store = live_store({"naukri": rules(max_applies_per_day=1, max_applies_per_hour=1),
                        "instahyre": rules("instahyre")})
    naukri = FakeAdapter("naukri", [job(1), job(2)])
    other = FakeAdapter("instahyre", [job(1, "instahyre", company="Other Co")])
    store.applied_at.append(("naukri", NOON_IST - timedelta(minutes=90)))
    pending = await store.upsert_discovered(job(9))
    await store.transition(pending, S.SCORED, "passed_filters")
    worker, _ = build(store, {"naukri": naukri, "instahyre": other})
    report = await worker.cycle()
    by = {p.platform: p for p in report.portals}
    assert by["naukri"].skipped == "dashboard_daily_limit" and naukri.applied == []
    # Parked QUOTA_HIT_PENDING (reason recorded), then Phase 5 queues tomorrow's retry. With no
    # mail/enrichment wired the retry is still scheduled (no draft is invented).
    parked = store.records[("naukri", "naukri-9")]
    assert [e["reason"] for e in store.events if e["application_id"] == parked.id][-2:] == [
        "dashboard_daily_limit", "quota_hit_queued_draft_unavailable"]
    assert parked.state is S.DRAFTED_AND_QUEUED
    assert parked.retry_after == datetime(2026, 11, 27, 2, 30, tzinfo=UTC)  # 08:00 IST tomorrow
    assert by["instahyre"].applied == 1  # other portals keep running


async def test_daily_cap_reached_mid_cycle_stops_portal():
    store = live_store({"naukri": rules(max_applies_per_day=1, max_applies_per_hour=1)})
    adapter = FakeAdapter("naukri", [job(1), job(2), job(3)])
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].applied == 1 and report.portals[0].stopped_reason == "dashboard_daily_limit"
    assert len(adapter.applied) == 1


async def test_hourly_quota_skips_without_parking_jobs():
    store = live_store({"naukri": rules(max_applies_per_hour=1)})
    store.applied_at.append(("naukri", NOON_IST - timedelta(minutes=5)))
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].skipped == "dashboard_hourly_limit" and adapter.inspected == []
    assert store.records == {}


async def test_portal_native_limit_records_timestamp_and_parks_jobs():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1), job(2)], details={"naukri-1": {"portal_limit": "daily quota reached"}})
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].stopped_reason == "portal_daily_limit"
    assert store.rules["naukri"].portal_limit_hit_at is not None
    limited = store.records[("naukri", "naukri-1")]
    assert "portal_daily_limit" in [e["reason"] for e in store.events if e["application_id"] == limited.id]
    assert limited.state is S.DRAFTED_AND_QUEUED and limited.retry_after is not None  # Phase 5 retry queued
    assert adapter.applied == []
    again = await worker.cycle()  # same local day: portal stays parked
    assert again.portals[0].skipped == "portal_daily_limit"


async def test_auth_required_isolates_only_that_portal_with_single_hitl():
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    naukri = FakeAdapter("naukri", [job(1)], auth=AuthStatus.AUTH_REQUIRED)
    other = FakeAdapter("instahyre", [job(1, "instahyre")])
    worker, _ = build(store, {"naukri": naukri, "instahyre": other})
    first = await worker.cycle()
    await worker.cycle()
    by = {p.platform: p for p in first.portals}
    assert by["naukri"].skipped == "auth_required" and naukri.inspected == []
    assert by["instahyre"].applied == 1
    assert store.auth["naukri"] == "AUTH_REQUIRED"
    auth_rows = [h for h in store.hitl if h["kind"] == "AUTH"]
    assert len(auth_rows) == 1 and auth_rows[0]["platform"] == "naukri"
    assert "/resume naukri" in auth_rows[0]["prompt"]
    naukri.auth = AuthStatus.OK  # owner logged in again: stale AUTH request closed
    await worker.cycle()
    assert auth_rows[0]["status"] == "CANCELLED"


async def test_waiting_for_user_does_not_block_the_next_job():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1), job(2)], outcomes={"naukri-1": "question"})
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].waiting_for_user == 1 and report.portals[0].applied == 1
    assert store.records[("naukri", "naukri-1")].state is S.WAITING_FOR_USER
    assert store.records[("naukri", "naukri-2")].state is S.APPLIED
    assert store.hitl[0]["kind"] == "QUESTION" and store.hitl[0]["context"]["title"] == "Python Developer"
    await worker.cycle()
    assert [j for j, _ in adapter.applied].count("naukri-1") == 1  # not retried automatically


async def test_submission_unknown_and_applied_are_never_replayed():
    store = live_store({"naukri": rules()})
    for i, state in ((1, S.SUBMISSION_UNKNOWN), (2, S.APPLIED)):
        await store.upsert_discovered(job(i))
        store.records[("naukri", f"naukri-{i}")].state = state
    adapter = FakeAdapter("naukri", [job(1), job(2), job(3)])
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    assert adapter.inspected == ["naukri-3"] and [j for j, _ in adapter.applied] == ["naukri-3"]
    assert store.records[("naukri", "naukri-1")].state is S.SUBMISSION_UNKNOWN


async def test_exception_after_reservation_becomes_submission_unknown_and_loop_continues():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1), job(2)])
    original = adapter.apply_job

    async def flaky(page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        if detail.listing.external_job_id == "naukri-1":
            raise TimeoutError("browser crashed after click")
        return await original(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                              hitl_answers=hitl_answers)

    adapter.apply_job = flaky  # type: ignore[method-assign]
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert store.records[("naukri", "naukri-1")].state is S.SUBMISSION_UNKNOWN
    assert store.records[("naukri", "naukri-2")].state is S.APPLIED and report.portals[0].errors == 1
    await worker.cycle()
    assert [j for j, _ in adapter.applied].count("naukri-1") == 0


async def test_rules_and_preferences_reload_live_between_cycles():
    store = live_store({"naukri": rules(max_job_age_days=7)})
    adapter = FakeAdapter("naukri", [job(1)], details={"naukri-1": {"age": 10}})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    assert store.records[("naukri", "naukri-1")].state is S.FILTERED_OUT
    # Dashboard edit (no restart): disable the portal; then re-enable with a new target role.
    store.rules["naukri"] = replace(store.rules["naukri"], enabled=False)
    report = await worker.cycle()
    assert report.portals[0].skipped == "portal_disabled"
    store.rules["naukri"] = replace(store.rules["naukri"], enabled=True)
    store.profile = {"preferences": {"target_roles": ["Backend Engineer"]}}
    await worker.cycle()
    assert adapter.queries[-1] == "Backend Engineer"


async def test_filtered_jobs_record_reason_for_dashboard():
    store = live_store({"naukri": rules()})
    store.profile = {"preferences": {"company_blacklist": ["Company 1"], "keywords_excluded": ["php"]}}
    adapter = FakeAdapter("naukri", [job(1), job(2, title="PHP Developer"), job(3)],
                          details={"naukri-3": {"applicants": parse_applicants("450 applicants")}})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    reasons = {k[1]: r.reason for k, r in store.records.items()}
    assert reasons["naukri-1"] == "company_blacklisted: Company 1"
    assert reasons["naukri-2"] == "excluded_keyword_in_title: php"
    assert reasons["naukri-3"] == "applicants_over_limit"
    assert adapter.inspected == ["naukri-3"]  # card prefilter avoided opening 1 and 2


async def test_dry_run_never_clicks_apply_and_simulates_caps():
    store = live_store({"naukri": rules(max_applies_per_hour=2)})
    adapter = FakeAdapter("naukri", [job(i) for i in range(1, 5)])
    worker, _ = build(store, {"naukri": adapter}, force_dry_run=True)
    report = await worker.cycle()
    assert report.dry_run and all(dry for _, dry in adapter.applied)
    assert report.portals[0].would_apply == 2 and report.portals[0].stopped_reason == "dry_run_dashboard_hourly_limit"
    assert not any(r.state is S.APPLIED for r in store.records.values())
    assert store.records[("naukri", "naukri-1")].state is S.SCORED


async def test_dry_run_env_flag_forces_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    assert adapter.applied == [("naukri-1", True)]


async def test_auto_apply_disabled_only_scores_without_clicking():
    store = live_store({"naukri": rules(auto_apply_enabled=False)})
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert adapter.applied == [("naukri-1", True)] and report.portals[0].scored == 1
    await worker.cycle()
    assert adapter.inspected == ["naukri-1"]  # not re-opened every cycle


async def test_outside_active_hours_skips_portal():
    store = live_store({"naukri": rules(active_hours_start=time(8), active_hours_end=time(9))})
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert report.portals[0].skipped == "outside_active_hours" and adapter.inspected == []


async def test_restart_resumes_running_without_a_start_click():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1)])
    first, _ = build(store, {"naukri": adapter})
    del first  # simulated process crash/restart: only the DB row survives
    restarted, sleeps = build(store, {"naukri": adapter})

    async def stop_after_first_sleep(seconds):
        sleeps.calls.append(seconds)
        if seconds >= 5:
            restarted.stop_event.set()

    restarted._sleep = stop_after_first_sleep
    reports = await restarted.run()
    assert reports and reports[0].portals[0].applied == 1
    assert store.worker.observed_state == "OFFLINE" and store.worker.last_cycle_at is not None


@pytest.mark.parametrize("desired", [WorkerState.PAUSED, WorkerState.STOPPED])
async def test_paused_or_stopped_worker_does_not_cycle(desired):
    store = live_store({"naukri": rules()})
    store.worker.desired_state = desired
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})

    async def stop(seconds):
        worker.stop_event.set()

    worker._sleep = stop
    assert await worker.run() == [] and adapter.inspected == []
    assert worker.service.manager.closed == (1 if desired is WorkerState.STOPPED else 0)


async def test_run_once_request_runs_one_cycle_while_paused_and_clears_flag():
    store = live_store({"naukri": rules()})
    store.worker.desired_state = WorkerState.PAUSED
    await store.set_worker_control(run_once=True)
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})

    async def stop(seconds):
        worker.stop_event.set()

    worker._sleep = stop
    reports = await worker.run()
    assert len(reports) == 1 and store.worker.run_once_requested_at is None


async def test_pause_during_jitter_interrupts_before_next_application():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1), job(2)])
    worker, sleeps = build(store, {"naukri": adapter})

    async def pause_on_jitter(seconds):
        sleeps.calls.append(seconds)
        store.worker.desired_state = WorkerState.PAUSED

    worker._sleep = pause_on_jitter
    report = await worker.cycle()
    assert report.interrupted and [j for j, _ in adapter.applied] == ["naukri-1"]


async def test_once_mode_runs_exactly_one_cycle_regardless_of_desired_state():
    store = live_store({"naukri": rules()})
    store.worker.desired_state = WorkerState.STOPPED
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter}, force_dry_run=True)
    reports = await asyncio.wait_for(worker.run(once=True), timeout=5)
    assert len(reports) == 1 and adapter.applied == [("naukri-1", True)]


async def test_one_broken_portal_does_not_starve_the_others():
    store = live_store({"naukri": rules(), "instahyre": rules("instahyre")})
    broken = FakeAdapter("naukri", [job(1)])

    async def crash(page, *, query, limit=20, job_age_days=None):
        raise RuntimeError("Target page, context or browser has been closed")

    broken.discover_jobs = crash  # type: ignore[method-assign]
    other = FakeAdapter("instahyre", [job(1, "instahyre")])
    worker, _ = build(store, {"naukri": broken, "instahyre": other})
    report = await worker.cycle()
    by = {p.platform: p for p in report.portals}
    assert by["naukri"].skipped == "error: RuntimeError" and by["instahyre"].applied == 1
