"""Phase 6A on a disposable PostgreSQL 17 with migration 004 applied (fixture) and re-applied
twice more over live data: new portal_rules columns, mail_events dedup, restart-safe digest
date, candidate preference updates, and the LangGraph agent + event bus sharing ONE connection."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.agent_v2.control_graph import ControlAgent
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.digest import DigestScheduler
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import PostgresStore, SerializedConnection
from backend.app.events_v2.bus import PostgresBus
from backend.app.mail_v2.reader import MailEvent, MailEventStore
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector
from backend.tests.test_browser_v2_postgres_store import database  # noqa: F401 - module fixture
from backend.tests.test_v2_migration_sql import PG_BIN

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")
NOW = datetime(2026, 11, 26, 16, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def pg(database):  # noqa: F811
    import asyncpg

    connection = await asyncpg.connect(database)
    # The real candidate_profiles table carries version/updated_at (repository optimistic locking).
    await connection.execute("ALTER TABLE public.candidate_profiles ADD COLUMN IF NOT EXISTS version INT NOT NULL "
                             "DEFAULT 1, ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
    await connection.execute("TRUNCATE public.mail_events, public.email_drafts, public.application_state_events, "
                             "public.hitl_requests, public.applications CASCADE")
    await connection.execute("UPDATE public.portal_rules SET revision=1, enabled=(platform='naukri'), "
                             "max_applies_per_day=50, max_applies_per_hour=10, paused_until=NULL, "
                             "quota_fallback_daily_cap=10, quota_drafts_per_cycle=5")
    await connection.execute("UPDATE public.telegram_v2_state SET last_digest_on=NULL")
    yield connection
    await connection.close()


async def test_migration_reapplies_twice_over_live_data_with_phase6a_objects(pg):
    record = await PostgresStore(pg).upsert_discovered(JobListing(platform="naukri", external_job_id="keep-1",
                                                                  url="https://example.com/1"))
    sql = strip_pgvector(MIGRATION.read_text())
    for _ in range(2):
        await pg.execute(sql)
    assert await pg.fetchval("SELECT count(*) FROM public.applications WHERE id=$1", record.id) == 1
    columns = {r["column_name"]: r for r in await pg.fetch(
        "SELECT column_name, column_default, is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='portal_rules'")}
    assert columns["quota_fallback_daily_cap"]["column_default"] == "10"
    assert columns["quota_drafts_per_cycle"]["column_default"] == "5"
    assert columns["paused_until"]["is_nullable"] == "YES"
    assert await pg.fetchval("SELECT count(*) FROM public.portal_rules") == 15
    assert await pg.fetchval("SELECT to_regclass('public.mail_events') IS NOT NULL")
    assert await pg.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name='telegram_v2_state' "
                             "AND column_name='last_digest_on'") == 1
    assert await pg.fetchval("SELECT relforcerowsecurity FROM pg_class WHERE relname='mail_events'")
    assert await pg.fetchval("SELECT has_table_privilege('job_agent_runtime','public.mail_events','UPDATE')")
    assert not await pg.fetchval("SELECT has_table_privilege('job_agent_runtime','public.mail_events','DELETE')")
    with pytest.raises(Exception, match="quota_fallback_daily_cap"):
        await pg.execute("UPDATE public.portal_rules SET quota_fallback_daily_cap=101 WHERE platform='naukri'")


async def test_rules_quota_pause_and_preferences_round_trip(pg):
    store = PostgresStore(SerializedConnection(pg), owns_connection=False)
    rules = await store.get_rules("lever")
    assert (rules.quota_fallback_daily_cap, rules.quota_drafts_per_cycle, rules.paused_until) == (10, 5, None)
    until = NOW + timedelta(hours=3)
    updated = await store.update_rules("lever", {"quota_fallback_daily_cap": 3, "paused_until": until}, 1)
    assert updated.quota_fallback_daily_cap == 3 and updated.paused_until == until and updated.revision == 2
    prefs = await store.update_preferences({"company_blacklist": ["TCS"], "expected_ctc": 18})
    assert prefs["company_blacklist"] == ["TCS"] and prefs["target_roles"] == ["Python Developer"]
    assert await pg.fetchval("SELECT version FROM public.candidate_profiles WHERE singleton_key='primary'") >= 2
    with pytest.raises(ValueError, match="invalid_preferences"):
        await store.update_preferences({"expected_ctc": 5000})


async def test_mail_events_dedup_and_digest_date_survive_restarts(pg):
    events = MailEventStore(pg)
    assert await MailEventStore.ready(pg)
    event = MailEvent("<r1@acme>", "INTERVIEW", "imap", "hr@acme.example.com", "Interview", "Let's talk", NOW,
                      company_name="Acme")
    assert await events.add(event) and event.id
    assert not await events.add(MailEvent("<r1@acme>", "INTERVIEW", "imap", None, None, None, NOW))
    await events.mark_alerted("<r1@acme>")
    rows = await MailEventStore(pg).recent()
    assert len(rows) == 1 and rows[0].alerted_at is not None and rows[0].company_name == "Acme"
    store = PostgresStore(pg, owns_connection=False)
    first = DigestScheduler(store, hour=21)
    assert await first.due(NOW)  # 21:30 IST
    await first.mark_sent(NOW)
    assert not await DigestScheduler(store, hour=21).due(NOW + timedelta(minutes=10))  # new process, same day


async def test_agent_and_bus_share_the_single_serialized_connection(pg):
    serialized = SerializedConnection(pg)
    store = PostgresStore(serialized, owns_connection=False)
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="busy-1",
                                                      url="https://example.com/b", title="SDE", company="Acme"))
    before = await pg.fetchval("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'")
    bus = PostgresBus(serialized)
    agent = ControlAgent(store, event_bus=bus, clock=lambda: NOW)

    async def worker_job():
        moved = await store.transition(record, S.SCORED, "passed_filters")
        await asyncio.sleep(0)
        return await store.transition(moved, S.APPLYING, "apply_started", count_attempt=True)

    results = await asyncio.gather(agent.run("raise Naukri daily limit to 60"), agent.run("blacklist Infosys"),
                                   agent.run("pause Internshala for 2 hours"), worker_job())
    await bus.drain()
    assert all(r["ok"] for r in results[:3]), results
    assert results[3].state is S.APPLYING  # the in-flight job was never blocked or rolled back
    assert (await store.get_rules("naukri")).max_applies_per_day == 60
    assert (await store.get_rules("internshala")).paused_until == NOW + timedelta(hours=2)
    after = await pg.fetchval("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'")
    assert after == before  # no extra Supabase connection for LangGraph or the bus
    assert bus.published == 3 and bus.notify_errors == 0
    refused = await agent.run("re-apply to the Acme job")
    assert refused["verdict"] == "rejected" and (await store.get("naukri", "busy-1")).state is S.APPLYING
