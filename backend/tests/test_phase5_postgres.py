"""Phase 5 Layer 3 on a disposable PostgreSQL 17 with migration 004 applied.

10 seeded portals, enrichment_cache upsert/TTL, atomic enrichment_credits under
concurrency, email_drafts UNIQUE(application_id) + reservation semantics, and the
QUOTA_HIT_PENDING -> DRAFTED_AND_QUEUED -> SCORED -> APPLIED lifecycle surviving
store restarts with exactly one draft.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.quota import QuotaHitProcessor
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import PostgresStore, SerializedConnection
from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.service import EnrichmentService
from backend.app.enrichment_v2.store import (
    PostgresEnrichmentStore,
    enrichment_store_for,
)
from backend.tests.test_browser_v2_postgres_store import database  # noqa: F401 - module fixture
from backend.tests.test_mail_v2 import FakeIMAP
from backend.tests.test_mail_v2 import mail_service as build_mail
from backend.tests.test_v2_migration_sql import PG_BIN

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")
NOW = datetime.now(UTC).replace(microsecond=0)
NAUKRI = PortalRules(platform="naukri", enabled=True, auto_apply_enabled=True)


@pytest_asyncio.fixture
async def store(database):  # noqa: F811
    import asyncpg

    FakeIMAP.instances.clear()
    connection = await asyncpg.connect(database)
    await connection.execute(
        "TRUNCATE public.email_drafts, public.application_state_events, public.hitl_requests, "
        "public.applications, public.enrichment_cache, public.enrichment_credits CASCADE")
    yield PostgresStore(SerializedConnection(connection))
    await connection.close()


async def parked(store, i=1, jd="Apply via careers@acme.io"):
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"p5-{i}",
                                                      url=f"https://example.com/{i}", title="Python Developer",
                                                      company="Acme"))
    record = await store.transition(record, S.SCORED, "passed_filters", payload={"contact_hints": {"jd_excerpt": jd}})
    return await store.transition(record, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")


async def test_ten_portals_are_seeded_with_only_naukri_enabled(store):
    rules = {r.platform: r for r in await store.list_rules()}
    assert len(rules) == 10 and [p for p, r in rules.items() if r.enabled] == ["naukri"]
    assert {"work_at_a_startup", "we_work_remotely", "hiringcafe", "greenhouse", "lever"} <= set(rules)


async def test_enrichment_cache_upsert_ttl_and_status_constraint(store):
    import asyncpg

    cache = await enrichment_store_for(store)
    assert isinstance(cache, PostgresEnrichmentStore)
    await cache.put_cache("acme.io", status="NO_EMAIL_FOUND", emails=[], source="waterfall_exhausted",
                          expires_at=NOW + timedelta(days=7))
    await cache.put_cache("acme.io", status="FOUND", emails=[{"email": "hr@acme.io", "source": "jd_text"}],
                          source="jd_text", expires_at=NOW + timedelta(days=30), role_family="Backend")
    entry = await cache.get_cache("acme.io")
    assert (entry.status, entry.emails[0]["email"], entry.role_family) == ("FOUND", "hr@acme.io", "Backend")
    await cache.put_cache("old.io", status="FOUND", emails=[], source="x", expires_at=NOW - timedelta(days=1))
    assert await cache.cached_domains(NOW) == 1 and not (await cache.get_cache("old.io")).valid(NOW)
    with pytest.raises(asyncpg.CheckViolationError):
        await store.connection.execute(
            "INSERT INTO public.enrichment_cache (company_domain, status) VALUES ('bad.io', 'MAYBE')")


async def test_credit_reservation_is_atomic_under_concurrency(store, database):  # noqa: F811
    import asyncpg

    connections = [await asyncpg.connect(database) for _ in range(5)]
    try:
        stores = [PostgresEnrichmentStore(c) for c in connections]
        results = await asyncio.gather(*(s.reserve_credit("apollo", "2026-11-26", 2) for s in stores))
    finally:
        for connection in connections:
            await connection.close()
    assert sorted(results) == [False, False, False, True, True]
    cache = PostgresEnrichmentStore(store.connection)
    row = await cache.credit("apollo", "2026-11-26")
    assert (row.used, row.limit_cap) == (2, 2)
    await cache.set_cooldown("apollo", "2026-11-26", 2, NOW + timedelta(hours=24), "http_403_plan_restricted")
    await cache.set_cooldown("apollo", "2026-11-27", 2, NOW + timedelta(hours=1), "x")
    assert await cache.cooldown_until("apollo") == NOW + timedelta(hours=24)
    assert (await cache.credit("apollo", "2026-11-26")).used == 2  # cooldown never resets usage


async def test_email_drafts_unique_application_and_reservation_semantics(store):
    import asyncpg

    record = await parked(store)
    first = await store.reserve_email_draft(record.id, "naukri", "hr@acme.io")
    second = await store.reserve_email_draft(record.id, "naukri", "other@acme.io")
    assert first.reserved and not second.reserved and second.draft.status == "PENDING"
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.connection.execute(
            "INSERT INTO public.email_drafts (application_id, channel) VALUES ($1::uuid, 'imap')", record.id)
    with pytest.raises(asyncpg.CheckViolationError):
        await store.connection.execute("UPDATE public.email_drafts SET status='CREATED' WHERE id=$1::uuid",
                                       first.draft.id)
    await store.fail_email_draft(first.draft.id, "imap_auth_failed")
    retry = await store.reserve_email_draft(record.id, "naukri", "hr@acme.io")
    assert retry.reserved and retry.draft.id == first.draft.id  # a definite failure may be re-claimed
    done = await store.complete_email_draft(retry.draft.id, channel="imap", subject="S", body_preview="B" * 900,
                                            composer="template", enrichment_source="jd_text",
                                            external_draft_id="<x@example.com>")
    assert done.status == "CREATED" and len(done.body_preview) == 280
    assert (await store.get_application(record.id)).draft_created_at is not None
    assert not (await store.reserve_email_draft(record.id, "naukri", "hr@acme.io")).reserved
    assert await store.count_email_drafts("CREATED", "naukri") == 1


async def test_quota_lifecycle_survives_restarts_with_exactly_one_draft(store, database):  # noqa: F811
    import asyncpg

    record = await parked(store)
    clock = datetime(2026, 11, 26, 6, 30, tzinfo=UTC)
    enrichment = EnrichmentService(await enrichment_store_for(store),
                                   config=EnrichmentConfig(keys={}, fetch_pages=False), clock=lambda: clock)
    processor = QuotaHitProcessor(store, enrichment=enrichment, mail=build_mail(store), clock=lambda: clock)
    report = await processor.process(NAUKRI, {}, quota_exhausted=True)
    assert (report.drafted, report.queued) == (1, 1)
    assert await store.parked_since("naukri", NOW - timedelta(hours=1)) == 1  # events use the DB clock

    restarted_connection = await asyncpg.connect(database)  # new worker process
    try:
        restarted = PostgresStore(SerializedConnection(restarted_connection))
        queued = await restarted.get_application(record.id)
        assert queued.state is S.DRAFTED_AND_QUEUED and queued.retry_after == datetime(2026, 11, 27, 2, 30,
                                                                                         tzinfo=UTC)
        assert await restarted.due_retries("naukri", clock) == []
        (due,) = await restarted.due_retries("naukri", clock + timedelta(days=1))
        due = await restarted.transition(due, S.SCORED, "quota_retry_due")
        due = await restarted.transition(due, S.APPLYING, "apply_started", count_attempt=True)
        applied = await restarted.transition(due, S.APPLIED, "confirmation_text", receipt={"source": "test"})
        assert applied.state is S.APPLIED and applied.draft_created_at is not None
        rows, total = await restarted.list_email_drafts("naukri")
        assert total == 1 and rows[0].application_state == "APPLIED" and rows[0].recipient_email == "careers@acme.io"
        events = [e["event_type"] for e in await restarted.application_events(record.id)]
        assert events == ["passed_filters", "dashboard_daily_limit", "quota_hit_drafted_and_queued",
                          "quota_retry_due", "apply_started", "confirmation_text"]
    finally:
        await restarted_connection.close()
    assert sum(1 for i in FakeIMAP.instances for c in i.calls if c[0] == "append") == 1


async def test_phase6a_dashboard_quota_columns_drive_the_processor(store):
    """quota_drafts_per_cycle / quota_fallback_daily_cap are live portal_rules columns (Phase 6A)."""
    from backend.app.browser_v2.quota import fallback_daily_cap

    for i in range(3):
        await parked(store, 60 + i)
    rules = await store.get_rules("naukri")
    assert (rules.quota_fallback_daily_cap, rules.quota_drafts_per_cycle) == (10, 5)
    rules = await store.update_rules("naukri", {"quota_drafts_per_cycle": 1, "quota_fallback_daily_cap": 2},
                                     rules.revision)
    assert fallback_daily_cap(rules) == 2
    report = await QuotaHitProcessor(store, clock=lambda: NOW).process(rules, {}, quota_exhausted=True)
    assert report.queued == 1 and await store.count_state(S.QUOTA_HIT_PENDING, "naukri") == 2
    await store.update_rules("naukri", {"quota_drafts_per_cycle": 5, "quota_fallback_daily_cap": 10},
                             rules.revision)
