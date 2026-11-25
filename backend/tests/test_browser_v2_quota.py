"""Phase 5 Layer 1: QuotaHitProcessor + worker quota path (draft once, retry tomorrow)."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.quota import (
    QuotaHitProcessor,
    hints_from_events,
    next_daily_reset,
    quota_summary,
)
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.state import InvalidTransition, check_transition
from backend.app.browser_v2.store import MemoryStore
from backend.app.browser_v2.worker import Worker
from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.service import EnrichmentService
from backend.app.mail_v2.service import MailDraftService
from backend.tests.test_browser_v2_worker import (
    NOON_IST,
    FakeAdapter,
    Sleeps,
    job,
    live_store,
    rules,
)
from backend.tests.test_mail_v2 import IMAP, FakeIMAP, factory
from backend.tests.test_mail_v2 import mail_service as build_mail

NAUKRI = PortalRules(platform="naukri", enabled=True, auto_apply_enabled=True)


@pytest.fixture(autouse=True)
def reset_fake():
    FakeIMAP.instances.clear()


def test_next_daily_reset_is_tomorrow_at_active_start_in_portal_timezone():
    assert next_daily_reset(NAUKRI, NOON_IST) == datetime(2026, 11, 27, 2, 30, tzinfo=UTC)  # 08:00 IST
    late = datetime(2026, 11, 26, 18, 45, tzinfo=UTC)  # 00:15 IST on the 27th
    assert next_daily_reset(NAUKRI, late) == datetime(2026, 11, 28, 2, 30, tzinfo=UTC)
    all_day = PortalRules(platform="naukri", active_hours_start=None, active_hours_end=None)
    assert next_daily_reset(all_day, NOON_IST) == datetime(2026, 11, 26, 18, 35, tzinfo=UTC)  # 00:05 IST
    early = PortalRules(platform="naukri", active_hours_start=time(0, 0))
    assert next_daily_reset(early, NOON_IST).astimezone(ZoneInfo("Asia/Kolkata")).time() == time(0, 5)


def test_state_machine_allows_the_next_day_retry_and_keeps_never_replay():
    check_transition(S.DRAFTED_AND_QUEUED, S.SCORED)
    check_transition(S.DRAFTED_AND_QUEUED, S.DRAFTED_AND_QUEUED)  # reschedule
    for terminal in (S.APPLIED, S.SUBMISSION_UNKNOWN):
        with pytest.raises(InvalidTransition):
            check_transition(terminal, S.DRAFTED_AND_QUEUED)


def test_quota_summary_message():
    text = quota_summary(NAUKRI, 3, 5, datetime(2026, 11, 27, 2, 30, tzinfo=UTC))
    assert text == "Naukri daily limit hit — created 3 Gmail drafts & queued 5 jobs for tomorrow 08:00 IST"


def test_hints_come_from_the_latest_event_payload():
    events = [{"payload": {"contact_hints": {"jd_excerpt": "old"}}}, {"payload": {}},
              {"payload": {"contact_hints": {"jd_excerpt": "new"}}}]
    assert hints_from_events(events) == {"jd_excerpt": "new"} and hints_from_events(None) == {}


async def parked(store, i=1, jd="Write to careers@acme.io", reason="dashboard_daily_limit", platform="naukri"):
    record = await store.upsert_discovered(JobListing(platform=platform, external_job_id=f"{platform}-{i}",
                                                      url=f"https://example.com/{i}", title="Python Developer",
                                                      company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters", payload={"contact_hints": {"jd_excerpt": jd}})
    return await store.transition(record, S.QUOTA_HIT_PENDING, reason)


def processor(store, *, mail=True, clock=NOON_IST, per_cycle=5):
    enrichment = EnrichmentService(config=EnrichmentConfig(keys={}, fetch_pages=False), clock=lambda: clock)
    return QuotaHitProcessor(store, enrichment=enrichment, mail=build_mail(store) if mail else None,
                             clock=lambda: clock, drafts_per_cycle=per_cycle)


async def test_processor_drafts_once_and_queues_tomorrow():
    store = MemoryStore(profile={"full_name": "Test Candidate"})
    record = await parked(store)
    report = await processor(store).process(NAUKRI, store.profile, quota_exhausted=True)
    fresh = await store.get_application(record.id)
    assert (fresh.state, fresh.reason) == (S.DRAFTED_AND_QUEUED, "quota_hit_drafted_and_queued")
    assert fresh.retry_after == datetime(2026, 11, 27, 2, 30, tzinfo=UTC) and fresh.draft_created_at
    assert (report.drafted, report.queued) == (1, 1) and store.drafts[0]["recipient_email"] == "careers@acme.io"
    event = store.events[-1]
    assert event["payload"]["channel"] == "imap" and "careers@acme.io" not in str(event["payload"])


async def test_no_email_still_queues_and_never_creates_an_empty_draft():
    store = MemoryStore()
    record = await parked(store, jd="No contact details.")
    report = await processor(store).process(NAUKRI, {}, quota_exhausted=True)
    fresh = await store.get_application(record.id)
    assert (fresh.state, fresh.reason) == (S.DRAFTED_AND_QUEUED, "quota_hit_queued_no_email")
    assert store.events[-1]["payload"]["draft_reason"] == "quota_hit_no_recruiter_email"
    assert store.drafts == [] and FakeIMAP.instances == [] and report.no_email == 1


async def test_second_quota_hit_reuses_the_existing_draft():
    store = MemoryStore()
    record = await parked(store)
    await processor(store).process(NAUKRI, {}, quota_exhausted=True)
    record = await store.get_application(record.id)
    record = await store.transition(record, S.SCORED, "quota_retry_due")
    await store.transition(record, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")
    tomorrow = NOON_IST + timedelta(days=1)
    report = await processor(store, clock=tomorrow).process(NAUKRI, {}, quota_exhausted=True)
    fresh = await store.get_application(record.id)
    assert fresh.reason == "quota_hit_queued_already_drafted" and report.already_drafted == 1
    assert fresh.retry_after == datetime(2026, 11, 28, 2, 30, tzinfo=UTC)
    assert len(store.drafts) == 1 and sum(1 for i in FakeIMAP.instances for c in i.calls if c[0] == "append") == 1


async def test_stale_jobs_expire_instead_of_retrying_forever():
    store = MemoryStore()
    record = await parked(store)
    store.records[("naukri", "naukri-1")].created_at = NOON_IST - timedelta(days=7)
    report = await processor(store).process(NAUKRI, {}, quota_exhausted=True)
    assert (await store.get_application(record.id)).state is S.FILTERED_OUT and report.expired == 1
    assert store.drafts == []


async def test_overdue_retries_are_rescheduled_only_while_quota_is_exhausted():
    store = MemoryStore()
    record = await parked(store)
    await processor(store, mail=False).process(NAUKRI, {}, quota_exhausted=True)
    later = NOON_IST + timedelta(days=1, hours=1)
    report = await processor(store, mail=False, clock=later).process(NAUKRI, {}, quota_exhausted=False)
    assert report.rescheduled == 0 and (await store.get_application(record.id)).retry_after < later
    report = await processor(store, mail=False, clock=later).process(NAUKRI, {}, quota_exhausted=True)
    fresh = await store.get_application(record.id)
    assert report.rescheduled == 1 and fresh.reason == "quota_hit_rescheduled" and fresh.retry_after > later


async def test_processing_is_bounded_per_cycle():
    store = MemoryStore()
    for i in range(4):
        await parked(store, i)
    report = await processor(store, mail=False, per_cycle=3).process(NAUKRI, {}, quota_exhausted=True)
    assert report.queued == 3 and await store.count_state(S.QUOTA_HIT_PENDING) == 1


# --- worker integration ------------------------------------------------------------------
def worker_for(store, adapters, *, notify=None, mail=True):
    from backend.app.browser_v2.service import BrowserService
    from backend.tests.test_browser_v2_worker import FakeManager

    service = BrowserService(FakeManager(), store, adapters=adapters)  # type: ignore[arg-type]
    quota = processor(store, mail=mail)
    quota.clock = lambda: NOON_IST
    return Worker(service, clock=lambda: NOON_IST, sleeper=Sleeps(), idle_poll_sec=5, quota=quota, notify=notify)


async def test_quota_hit_inspects_a_few_new_jobs_parks_drafts_and_notifies_once():
    store = live_store({"naukri": rules(max_applies_per_day=1, max_applies_per_hour=1)})
    store.applied_at.append(("naukri", NOON_IST - timedelta(minutes=90)))
    adapter = FakeAdapter("naukri", [job(1), job(2)],
                          details={"naukri-1": {"description": "python fastapi. Apply: hr@company1.com"}})
    messages: list[str] = []

    async def notify(text):
        messages.append(text)

    worker = worker_for(store, {"naukri": adapter}, notify=notify)
    report = await worker.cycle()
    portal = report.portals[0]
    assert portal.skipped == "dashboard_daily_limit" and adapter.applied == []  # never clicked Apply
    assert set(adapter.inspected) == {"naukri-1", "naukri-2"} and portal.drafted == 1
    states = {k[1]: r.state for k, r in store.records.items()}
    assert states == {"naukri-1": S.DRAFTED_AND_QUEUED, "naukri-2": S.DRAFTED_AND_QUEUED}
    assert messages == ["Naukri daily limit hit — created 1 Gmail draft & queued 2 jobs for tomorrow 08:00 IST"]
    await worker.cycle()
    assert len(messages) == 1  # throttled: once per portal per day


async def test_due_retry_runs_before_new_discoveries_and_applies():
    store = live_store({"naukri": rules()})
    record = await parked(store, 7)
    record = await store.transition(record, S.DRAFTED_AND_QUEUED, "quota_hit_queued_no_email",
                                    retry_after=NOON_IST - timedelta(minutes=1))
    adapter = FakeAdapter("naukri", [job(1)])
    report = await worker_for(store, {"naukri": adapter}).cycle()
    assert report.portals[0].retried == 1 and adapter.inspected[0] == "naukri-7"
    assert (await store.get_application(record.id)).state is S.APPLIED
    reasons = [e["reason"] for e in store.events if e["application_id"] == record.id]
    assert "quota_retry_due" in reasons and reasons[-1] == "confirmation_text"


async def test_retry_not_yet_due_is_left_alone():
    store = live_store({"naukri": rules()})
    record = await parked(store, 7)
    await store.transition(record, S.DRAFTED_AND_QUEUED, "quota_hit_queued_no_email",
                           retry_after=NOON_IST + timedelta(hours=20))
    adapter = FakeAdapter("naukri", [])
    report = await worker_for(store, {"naukri": adapter}).cycle()
    assert report.portals[0].retried == 0 and adapter.inspected == []


async def test_dry_run_never_drafts_or_retries():
    store = live_store({"naukri": rules()})
    store.worker.dry_run = True
    record = await parked(store, 7)
    await store.transition(record, S.DRAFTED_AND_QUEUED, "x", retry_after=NOON_IST - timedelta(hours=1))
    second = await parked(store, 8)
    adapter = FakeAdapter("naukri", [])
    await worker_for(store, {"naukri": adapter}).cycle()
    assert (await store.get_application(second.id)).state is S.QUOTA_HIT_PENDING and store.drafts == []
    assert (await store.get_application(record.id)).state is S.DRAFTED_AND_QUEUED


async def test_mail_service_wiring_is_read_and_draft_only():
    service = MailDraftService(MemoryStore(), IMAP)
    assert service.status()["permission"] == "READ_AND_DRAFT_ONLY" and service.imap.factory is not factory
