"""Followup 007 + Phase 1 repo methods against a disposable PostgreSQL 17 (004 -> 005 -> 007 x2).

Same contract as the MemoryStore twins (test_telegram_notify_router_v2 / test_phase1_regressions)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, PostgresStore
from backend.app.operations.v2_schema import FOLLOWUP_MIGRATIONS, PHASE9_MIGRATION
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector
from backend.tests.test_browser_v2_postgres_store import BOOTSTRAP
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pgnotify")
    data, port = tmp / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust"],
                   check=True, capture_output=True)
    server = subprocess.Popen([str(PG_BIN / "postgres"), "-D", str(data), "-p", str(port), "-k", "",
                               "-c", "listen_addresses=127.0.0.1"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    psql = [str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q"]
    try:
        for _ in range(100):
            if subprocess.run([*psql, "-c", "SELECT 1"], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(0.1)
        subprocess.run([*psql, "-c", BOOTSTRAP], check=True, capture_output=True)
        core = tmp / "004.sql"
        core.write_text(strip_pgvector(MIGRATION.read_text()))
        # 006 needs the pgvector semantic_cache table (stripped here); test_semantic_cache_v2_store_pg covers it.
        followups = [core, PHASE9_MIGRATION, FOLLOWUP_MIGRATIONS["007"], FOLLOWUP_MIGRATIONS["007"]]  # idempotent
        for path in followups:
            subprocess.run([*psql, "-f", str(path)], check=True, capture_output=True, text=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest_asyncio.fixture
async def stores(database):
    import asyncpg

    pg = PostgresStore(await asyncpg.connect(database))
    await pg.connection.execute(
        "TRUNCATE public.telegram_notification_ledger, public.telegram_digest_queue, public.hitl_requests, "
        "public.application_state_events, public.applications CASCADE")
    await pg.connection.execute("UPDATE public.telegram_v2_state SET last_digest_slot=NULL, muted_until=NULL")
    yield [pg, MemoryStore()]
    await pg.close()


NOW = datetime(2026, 11, 28, 6, 30, tzinfo=UTC)


async def test_ledger_cooldown_suppression_and_resolve_contract(stores):
    for store in stores:
        entry = await store.ledger_record("err:naukri:timeout", topic="system.error", priority=1, now=NOW,
                                          sent=True, chat_id=42, message_id=7)
        assert (entry.last_sent_at, entry.message_id, entry.suppressed_count) == (NOW, 7, 0)
        entry = await store.ledger_record("err:naukri:timeout", topic="system.error", priority=1,
                                          now=NOW + timedelta(minutes=5), sent=False, suppressed=True)
        assert entry.suppressed_count == 1 and entry.last_sent_at == NOW and entry.message_id == 7
        resolved = await store.ledger_resolve("err:naukri:timeout", NOW + timedelta(hours=1))
        assert resolved is not None and resolved.resolved_at is not None
        assert await store.ledger_resolve("err:naukri:timeout", NOW) is None  # once
        entry = await store.ledger_record("err:naukri:timeout", topic="system.error", priority=1,
                                          now=NOW + timedelta(hours=3), sent=True, message_id=9)
        assert entry.suppressed_count == 0 and entry.resolved_at is None and entry.message_id == 9
        assert await store.ledger_get("missing:key") is None
        with pytest.raises(ValueError):
            await store.ledger_get("BAD KEY")


async def test_digest_queue_and_slot_claim_contract(stores):
    for store in stores:
        await store.digest_enqueue("job.applied", 2, "✅ applied: naukri SWE", "applied:naukri:1")
        await store.digest_enqueue("system.error", 1, "x" * 2000)
        pending = await store.digest_pending()
        assert [item.priority for item in pending] == [1, 2] and len(pending[0].text) <= 600
        assert await store.digest_mark_delivered([item.id for item in pending], NOW) == 2
        assert await store.digest_pending() == []
        assert await store.claim_digest_slot("2026-11-28T09", None) is True
        assert await store.claim_digest_slot("2026-11-28T09", None) is False  # CAS: already claimed
        assert await store.claim_digest_slot("2026-11-28T21", "2026-11-28T09") is True
        state = await store.update_telegram_state(muted_until=NOW + timedelta(hours=2))
        assert state.muted_until == NOW + timedelta(hours=2)


async def test_closed_hitl_card_sync_and_phase1_queries_contract(stores):
    for store in stores:
        record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="77",
                                                          url="https://example.com/77", title="SWE", company="A"))
        record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
        assert [r.external_job_id for r in await store.stale_applying(datetime.now(UTC) + timedelta(minutes=1))] \
            == ["77"]
        assert await store.stale_applying(datetime.now(UTC) - timedelta(minutes=30)) == []
        record = await store.transition(record, S.SUBMISSION_UNKNOWN, "confirmation_ambiguous")
        since = datetime.now(UTC) - timedelta(hours=1)
        assert await store.ambiguous_submits_since("naukri", since) == 1
        hitl_id = await store.create_hitl(record, "naukri", "QUESTION", "Why?", {})
        await store.mark_hitl_delivered(hitl_id, 555)
        assert await store.unsynced_closed_hitl() == []  # still OPEN
        await store.close_hitl(hitl_id, "ANSWERED", "Because", "dashboard")
        rows = await store.unsynced_closed_hitl()
        assert [r.id for r in rows] == [hitl_id] and rows[0].resolved_via == "dashboard"
        await store.mark_hitl_card_closed(hitl_id)
        assert await store.unsynced_closed_hitl() == []
