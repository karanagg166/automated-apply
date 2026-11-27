"""Phase 1 (2026-11-28 production-hardening audit): one regression test per verified P0/P1 bug."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from backend.app.browser_v2.service.helpers import quota_counts
from backend.app.browser_v2.state import ApplicationState as S
from backend.tests.test_browser_v2_worker import (
    NOON_IST,
    FakeAdapter,
    build,
    job,
    live_store,
    rules,
)


@pytest.fixture(autouse=True)
def no_dry_env(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)


async def _stuck_applying(store, worker):
    """Reserve APPLYING the way the service does, then 'crash' before writing the outcome."""
    record = store.records[("naukri", "naukri-1")]
    reserved = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    store.records[("naukri", "naukri-1")].updated_at = NOON_IST - timedelta(minutes=30)
    return reserved


async def test_stale_applying_row_is_recovered_as_submission_unknown_at_boot():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    await store.upsert_discovered(job(1))
    await store.transition(store.records[("naukri", "naukri-1")], S.SCORED, "scored")
    await _stuck_applying(store, worker)

    await worker.recover_stale_applying(NOON_IST)

    record = store.records[("naukri", "naukri-1")]
    assert record.state is S.SUBMISSION_UNKNOWN and record.reason == "stale_applying_recovered"
    await worker.cycle()
    assert adapter.applied == []  # never replayed


async def test_fresh_applying_row_is_left_alone():
    store = live_store({"naukri": rules()})
    worker, _ = build(store, {"naukri": FakeAdapter("naukri", [])})
    await store.upsert_discovered(job(1))
    await store.transition(store.records[("naukri", "naukri-1")], S.SCORED, "scored")
    await store.transition(store.records[("naukri", "naukri-1")], S.APPLYING, "apply_started")
    store.records[("naukri", "naukri-1")].updated_at = NOON_IST - timedelta(minutes=2)
    await worker.recover_stale_applying(NOON_IST)
    assert store.records[("naukri", "naukri-1")].state is S.APPLYING


async def test_cancellation_after_reservation_writes_submission_unknown():
    """SIGTERM (CancelledError) mid-apply used to skip the `except Exception` and leave APPLYING."""
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1)])

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    adapter.apply_job = cancelled  # type: ignore[method-assign]
    worker, _ = build(store, {"naukri": adapter})
    with pytest.raises(asyncio.CancelledError):
        await worker.cycle()
    record = store.records[("naukri", "naukri-1")]
    assert record.state is S.SUBMISSION_UNKNOWN
    assert record.reason == "exception_after_reservation:CancelledError"


async def test_outcome_write_failure_after_click_does_not_strand_applying():
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1)])
    worker, _ = build(store, {"naukri": adapter})
    original = store.transition

    async def flaky(record, target, reason, **kw):
        if target is S.APPLIED:
            raise ConnectionError("db blip")
        return await original(record, target, reason, **kw)

    store.transition = flaky  # type: ignore[method-assign]
    await worker.cycle()
    record = store.records[("naukri", "naukri-1")]
    assert record.state is S.SUBMISSION_UNKNOWN and record.reason == "outcome_write_failed:ConnectionError"


async def test_daily_cap_counts_ambiguous_submit_attempts():
    """Every `confirmation_ambiguous` SUBMISSION_UNKNOWN may be a real send: the cap must count it."""
    store = live_store({"naukri": rules(max_applies_per_day=2)})
    for i in (1, 2):
        await store.upsert_discovered(job(i))
        record = await store.transition(store.records[("naukri", f"naukri-{i}")], S.SCORED, "scored")
        record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
        await store.transition(record, S.SUBMISSION_UNKNOWN, "confirmation_ambiguous")
    from datetime import UTC, datetime

    counts = await quota_counts(store, await store.get_rules("naukri"), datetime.now(UTC))
    assert counts["applied_today"] == 0 and counts["attempts_today"] == 2
    assert counts["daily_limit_hit"] is True


# --- browser manager: crash relaunch + driver leak (P1) ----------------------------------------
class _Ctx:
    def __init__(self, fail_new_page: bool = False):
        self.pages: list = []
        self.handlers: dict = {}
        self.fail_new_page = fail_new_page
        self.closed = False

    def on(self, event, handler):
        self.handlers[event] = handler

    async def route(self, *_):
        return None

    async def cookies(self):
        return []

    async def add_cookies(self, *_):
        return None

    async def new_page(self):
        if self.fail_new_page:
            raise RuntimeError("TargetClosedError: Target page, context or browser has been closed")
        page = _Page(self)
        self.pages.append(page)
        return page

    async def close(self):
        if self.fail_new_page:
            raise RuntimeError("browser has disconnected")
        self.closed = True


class _Page:
    def __init__(self, ctx):
        self.ctx, self._closed = ctx, False

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True


class _Playwright:
    def __init__(self, fail_launch: int = 0):
        self.chromium = self
        self.fail_launch = fail_launch
        self.contexts: list[_Ctx] = []
        self.stopped = 0

    async def start(self):
        return self

    async def stop(self):
        self.stopped += 1

    async def launch_persistent_context(self, user_data_dir, **options):
        if self.fail_launch:
            self.fail_launch -= 1
            raise RuntimeError("launch failed")
        ctx = _Ctx()
        self.contexts.append(ctx)
        return ctx


def _manager(tmp_path, fake):
    from backend.app.browser_v2.manager import BraveBrowserManager

    executable = tmp_path / "Brave Browser"
    executable.write_text("")
    manager = BraveBrowserManager(user_data_dir=tmp_path / "brave", executable=executable,
                                  playwright_factory=lambda: fake)
    manager.background = False
    return manager


async def test_crashed_brave_is_relaunched_on_next_page(tmp_path):
    fake = _Playwright()
    manager = _manager(tmp_path, fake)
    await manager.page()
    first = fake.contexts[0]
    first.handlers["close"]()  # Brave crashed / was killed
    first.fail_new_page = True
    page = await manager.page()
    assert len(fake.contexts) == 2 and page.ctx is fake.contexts[1] and manager.relaunches == 1
    await manager.close()


async def test_dead_context_new_page_error_triggers_one_relaunch(tmp_path):
    fake = _Playwright()
    manager = _manager(tmp_path, fake)
    await manager.page()
    fake.contexts[0].fail_new_page = True
    manager._worker._closed = True  # the tab died with the browser; no close event was delivered
    page = await manager.page()
    assert page.ctx is fake.contexts[1] and manager.relaunches == 1


async def test_failed_launch_stops_the_playwright_driver(tmp_path):
    fake = _Playwright(fail_launch=1)
    manager = _manager(tmp_path, fake)
    with pytest.raises(RuntimeError, match="launch failed"):
        await manager.start()
    assert fake.stopped == 1 and manager._playwright is None and not manager.running
    await manager.start()
    assert manager.running


async def test_close_stops_driver_even_when_dead_context_close_raises(tmp_path):
    fake = _Playwright()
    manager = _manager(tmp_path, fake)
    await manager.start()
    fake.contexts[0].fail_new_page = True  # its close() raises too
    await manager.close()
    assert fake.stopped == 1 and not manager.running


# --- single-instance worker + fail-safe DRY_RUN (P1) -------------------------------------------
def test_second_worker_instance_is_refused(tmp_path):
    from backend.app.browser_v2.worker.instance_lock import (
        WorkerAlreadyRunning,
        instance_lock,
    )

    with instance_lock("worker-v2", directory=tmp_path):
        with pytest.raises(WorkerAlreadyRunning, match="worker-v2_already_running"):
            with instance_lock("worker-v2", directory=tmp_path):
                pass
    with instance_lock("worker-v2", directory=tmp_path):  # released on exit
        pass


def test_dry_run_in_project_env_file_forces_dry_run(monkeypatch):
    from backend.app.browser_v2.worker.reports import env_forces_dry_run

    monkeypatch.delenv("DRY_RUN", raising=False)
    assert env_forces_dry_run({"DRY_RUN": "true"}) is True
    assert env_forces_dry_run({"DRY_RUN": "false"}) is False
    assert env_forces_dry_run() is False
    monkeypatch.setenv("DRY_RUN", "1")
    assert env_forces_dry_run({}) is True


# --- hosted ATS applier never fills PII off the vetted host (P1) ------------------------------
class _NeverFill:
    async def fill(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("PII/resume filled on a non-ATS host")


class _RedirectedPage:
    def __init__(self, url):
        self.url = url
        self.gotos: list[str] = []

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = "https://careers.acme.example/apply?from=greenhouse"  # server-side redirect

    async def wait_for_timeout(self, ms):
        return None


def _gh_detail():
    from backend.app.browser_v2.adapters.base import JobDetail, JobListing

    url = "https://job-boards.greenhouse.io/acme/jobs/4012345"
    listing = JobListing(platform="greenhouse", external_job_id="4012345", url=url, title="Backend Engineer",
                         company="Acme")
    return JobDetail(listing=listing, applicants=None, posted_age_days=1, already_applied=False,
                     apply_mode="direct", description="python", apply_url=url, ats="greenhouse")


@pytest.mark.parametrize("dry_run", [True, False])
async def test_greenhouse_redirect_to_unknown_host_is_filtered_before_any_fill(dry_run):
    from backend.app.browser_v2.adapters.shared.apply_flow import HostedAtsApplier
    from backend.app.browser_v2.answers import CandidateFacts

    page = _RedirectedPage("about:blank")
    applier = HostedAtsApplier(_NeverFill(), settle_ms=0)  # type: ignore[arg-type]
    result = await applier.apply(page, _gh_detail(), CandidateFacts(), platform="greenhouse", dry_run=dry_run)
    assert result.state is S.FILTERED_OUT and result.reason == "ats_redirected:careers.acme.example"
    assert page.gotos and not result.clicked_apply


# --- owner HITL answers survive a job that did not run (P2) -----------------------------------
async def test_owner_answers_are_not_consumed_when_quota_stops_the_job_before_it_runs():
    from backend.app.browser_v2.hitl import HITLResolutionService
    from backend.tests.test_browser_v2_hitl_requeue import RecordingAdapter

    adapter = RecordingAdapter("naukri", [job(1)])
    store = live_store({"naukri": rules(max_delay_sec=45, max_applies_per_day=1)})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()  # naukri-1 asks a question -> WAITING_FOR_USER
    rows, _ = await store.list_hitl("OPEN")
    await HITLResolutionService(store).answer(rows[0].id, "2", cache_answer=False, via="telegram")
    other = await store.upsert_discovered(job(9))  # a confirmed apply elsewhere uses the daily cap of 1
    other = await store.transition(other, S.APPLYING, "apply_started")
    await store.transition(other, S.APPLIED, "confirmed")
    adapter.applied.clear()
    await worker.cycle()
    assert adapter.applied == []  # quota stopped it before process_job
    assert all(row["consumed_at"] is None for row in store.hitl if row["status"] == "ANSWERED")
    record = store.records[("naukri", "naukri-1")]
    assert await store.hitl_answers(record.id) == {"Notice period (days)?": "30"}  # kept for the real run


# --- secrets never leave via last_error / Telegram (P1 security) ------------------------------
def test_exception_text_is_scrubbed_of_tokens_dsns_and_keys():
    from backend.app.browser_v2.redact import describe_exception, redact_secrets

    token = "123456789:" + "A" * 35
    exc = ConnectionError(f"POST https://api.telegram.org/bot{token}/sendMessage failed; "
                          "dsn " + "postgresql" + "://runtime:" + "hunter2pass" + "@db.example.com:5432/postgres "
                          "url https://x.example/cb?code=abc123&state=1 Authorization: Bearer abcdefghijklmnop")
    text = describe_exception(exc)
    assert token not in text and "hunter2pass" not in text and "abc123" not in text
    assert "abcdefghijklmnop" not in text and text.startswith("ConnectionError: ")
    assert redact_secrets("gsk_" + "x" * 30) == "[REDACTED_KEY]"
    assert redact_secrets("plain timeout after 30s") == "plain timeout after 30s"


async def test_native_portal_limit_updates_the_cycle_snapshot_used_by_the_lane():
    from types import SimpleNamespace

    store = live_store({"naukri": rules()})
    worker, _ = build(store, {"naukri": FakeAdapter("naukri", [])})
    worker.ctx = SimpleNamespace(rules={"naukri": await store.get_rules("naukri")})  # type: ignore[assignment]
    assert worker.ctx.rules["naukri"].portal_limit_hit_at is None
    worker.note_portal_limit("naukri")
    snapshot = worker.ctx.rules["naukri"]
    assert snapshot.portal_limit_hit_at == NOON_IST
    assert await worker.service.quota_block("naukri", snapshot, NOON_IST)


# --- Phase 3: first-mover pipeline --------------------------------------------------------------
async def test_answered_hitl_job_is_requeued_at_top_priority_and_exempt_from_decay():
    from datetime import UTC, datetime

    from backend.app.browser_v2.hitl import HITLResolutionService
    from backend.tests.test_browser_v2_hitl_requeue import RecordingAdapter

    adapter = RecordingAdapter("naukri", [job(1)])
    store = live_store({"naukri": rules(max_delay_sec=45)})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    rows, _ = await store.list_hitl("OPEN")
    await HITLResolutionService(store).answer(rows[0].id, "2", cache_answer=False, via="dashboard")
    record = store.records[("naukri", "naukri-1")]
    assert (record.state, record.priority, record.priority_reason) == (S.SCORED, 0, "hitl_resumed")
    record.created_at = datetime.now(UTC) - timedelta(days=3)  # discovered long ago
    assert await store.decay_priorities(datetime.now(UTC)) == 0
    assert [r.external_job_id for r in await store.priority_candidates(datetime.now(UTC))] == ["naukri-1"]


async def test_watcher_gate_drops_blacklisted_and_cross_portal_duplicates_before_any_scoring():

    import httpx

    from backend.app.browser_v2.service import BrowserService
    from backend.tests.test_browser_v2_worker import FakeManager
    from backend.tests.test_watchers_v2 import GH, NOW, Harness, gh_job

    jobs = [gh_job(1, "Backend Engineer", NOW - timedelta(days=1))]
    h = Harness(lambda request: httpx.Response(200, json={"jobs": jobs}))
    h.store.profile = {"preferences": {"target_roles": ["backend engineer"], "company_blacklist": ["Acme"]}}
    service = BrowserService(FakeManager(), h.store, adapters={})  # type: ignore[arg-type]
    scored: list[str] = []

    def spy_score(listing, prefs, **kw):
        scored.append(listing.external_job_id)
        from backend.app.browser_v2.service.scoring import score_listing

        return score_listing(listing, prefs, **kw)

    h.hub.score_listing, h.hub.rule_gate = spy_score, service.watcher_gate

    async def prefs():
        return h.store.profile["preferences"]

    h.hub.prefs_provider = prefs
    await h.hub.poll_once(GH)  # baseline
    h.now = NOW + timedelta(minutes=3)
    jobs.append(gh_job(2, "Backend Engineer", h.now - timedelta(minutes=5)))
    outcome = await h.hub.poll_once(GH)
    assert outcome.skipped_by_rule == 1 and scored == [] and h.wakes == [] and h.events == []
    assert await h.store.get("greenhouse", "2") is None


async def test_applied_receipt_and_event_carry_first_mover_lag():
    from backend.app.events_v2.bus import InProcessBus

    store = live_store({"naukri": rules()})
    worker, _ = build(store, {"naukri": FakeAdapter("naukri", [job(1)])})
    bus = InProcessBus()
    seen: list[dict] = []

    async def on_applied(topic, payload):
        seen.append(payload)

    bus.subscribe("job.applied", on_applied)
    worker.service.event_bus = bus
    await worker.cycle()
    await bus.drain()
    timing = store.records[("naukri", "naukri-1")].receipt["timing"]
    assert timing["first_mover_lag_seconds"] is not None and timing["lag_from"] in {"posted_at", "discovered_at"}
    assert seen and seen[0]["first_mover_lag_seconds"] == timing["first_mover_lag_seconds"]


async def test_hung_job_is_capped_by_the_wall_clock_and_the_next_job_still_runs(monkeypatch):
    import backend.app.browser_v2.worker.executor as executor

    monkeypatch.setattr(executor, "JOB_WALL_CLOCK_SEC", 0.05)
    store = live_store({"naukri": rules()})
    adapter = FakeAdapter("naukri", [job(1), job(2)])
    original = adapter.apply_job

    async def hang_first(page, detail, profile, **kw):
        if detail.listing.external_job_id == "naukri-1":
            await asyncio.sleep(3600)
        return await original(page, detail, profile, **kw)

    adapter.apply_job = hang_first  # type: ignore[method-assign]
    worker, _ = build(store, {"naukri": adapter})
    report = await worker.cycle()
    assert store.records[("naukri", "naukri-1")].state is S.SUBMISSION_UNKNOWN  # reserved: never replayed
    assert store.records[("naukri", "naukri-2")].state is S.APPLIED and report.portals[0].errors == 1


async def test_portal_validation_error_quarantines_only_the_named_cache_backed_field():
    from types import SimpleNamespace

    from backend.app.browser_v2.adapters.shared.apply_flow import HostedAtsApplier

    quarantined: list[str] = []

    async def record(entry_id):
        quarantined.append(entry_id)

    filler = SimpleNamespace(answerer=SimpleNamespace(cache=SimpleNamespace(record_form_validation_error=record)))
    applier = HostedAtsApplier(filler, settle_ms=0)  # type: ignore[arg-type]
    answers = ({"question": "Notice period (in days)", "answer": "60", "cache_entry_id": "c1"},
               {"question": "Current location city", "answer": "Faridabad", "cache_entry_id": "c2"},
               {"question": "Email", "answer": "x@example.com"})
    count = await applier.quarantine_rejected(answers, ["Notice period must be one of 0, 15, 30 days"])
    assert count == 1 and quarantined == ["c1"]


async def test_stamp_cache_uses_the_exact_hash_the_worker_computes():
    from types import SimpleNamespace

    from backend.app.ai_v2.semantic_cache.keys import profile_version_hash
    from backend.app.browser_v2.answers import CandidateFacts
    from backend.app.browser_v2.facts_cli import stamp_cache
    from backend.app.browser_v2.store import MemoryStore

    calls: list[tuple] = []

    class Conn:
        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "UPDATE 58"

    store = MemoryStore(profile={"preferences": {"notice_period_days": 0, "expected_ctc": 12}})
    ai = SimpleNamespace(cache=SimpleNamespace(store=SimpleNamespace(connection=Conn())))
    result = await stamp_cache(store, ai, {})
    profile, reviewed = await store.load_profile()
    assert result == {"ok": True, "stamped": 58,
                      "profile_hash": profile_version_hash(CandidateFacts.from_profile(profile, reviewed))[:12]}
    assert "profile_version_hash IS NULL" in calls[0][0] and "source IN ('user','profile')" in calls[0][0]
