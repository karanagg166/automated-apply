"""Followup 008 + Milestone 2 funnel repo against a disposable PostgreSQL 17 (004 -> 005 -> 008 x2).

Same contract as the MemoryStore twin (test_mail_funnel_v2)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import OWNER_RELEASE_REASON
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, PostgresStore
from backend.app.mail_v2.event_store import MailEventStore
from backend.app.mail_v2.read_models import MailEvent
from backend.app.operations import v2_schema
from backend.app.operations.v2_schema import FOLLOWUP_MIGRATIONS, PHASE9_MIGRATION
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector
from backend.tests.test_browser_v2_postgres_store import BOOTSTRAP
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

pytestmark = pytest.mark.skipif(PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1",
                                reason="local PostgreSQL binaries not available")


def test_followup_008_is_registered_additive_and_idempotent():
    sql = FOLLOWUP_MIGRATIONS["008"].read_text()
    assert "DROP TABLE" not in sql.upper() and "DROP COLUMN" not in sql.upper() and "DELETE" not in sql.upper()
    assert "IF NOT EXISTS" in sql and "OA_INVITE" in sql
    assert v2_schema.ALL_TABLES == v2_schema.TABLES | v2_schema.PHASE9_TABLES | v2_schema.NOTIFY_TABLES  # no new table


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pgfunnel")
    data, port = tmp / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-E", "UTF8", "--locale=C", "-U", "postgres", "--auth=trust"],
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
        subprocess.run([*psql, "-f", str(core)], check=True, capture_output=True, text=True)
        # A pre-008 row survives the widening (no data loss), then 008 runs twice (idempotent).
        seed = "INSERT INTO public.mail_events (message_key, kind, source) VALUES ('pre-008', 'INTERVIEW', 'imap')"
        subprocess.run([*psql, "-c", seed], check=True, capture_output=True)
        for path in (PHASE9_MIGRATION, FOLLOWUP_MIGRATIONS["008"], FOLLOWUP_MIGRATIONS["008"]):
            subprocess.run([*psql, "-f", str(path)], check=True, capture_output=True, text=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


async def test_pre_008_rows_survive_the_widening(database):
    import asyncpg

    connection = await asyncpg.connect(database)
    try:
        assert await connection.fetchval("SELECT count(*) FROM public.mail_events WHERE message_key='pre-008'") == 1
        definition = await connection.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'mail_events_kind_check'")
        assert "OA_INVITE" in definition and "JOB_ALERT" in definition
    finally:
        await connection.close()


@pytest_asyncio.fixture
async def stores(database):
    import asyncpg

    pg = PostgresStore(await asyncpg.connect(database))
    await pg.connection.execute("TRUNCATE public.application_state_events, public.applications CASCADE")
    yield [pg, MemoryStore()]
    await pg.close()


async def unknown_row(store, i: int):
    record = await store.upsert_discovered(JobListing(platform="greenhouse", external_job_id=str(i),
                                                      url=f"https://example.com/{i}", title="Backend Engineer",
                                                      company="Acme"))
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    return await store.transition(record, S.SUBMISSION_UNKNOWN, "confirmation_ambiguous")


async def test_annotate_candidates_and_owner_release_contract(stores):
    since = datetime.now(UTC) - timedelta(days=1)
    for store in stores:
        row = await unknown_row(store, 1)
        assert [r.id for r in await store.mail_match_candidates(since)] == [row.id]
        assert await store.needs_reconciliation(datetime.now(UTC) + timedelta(minutes=1)) != []
        assert await store.needs_reconciliation(datetime.now(UTC) - timedelta(hours=1)) == []
        annotated = await store.annotate_application(row.id, "mail_oa_invite", {"message_key": "m1"},
                                                     {"email_verified": True})
        assert annotated.state == S.SUBMISSION_UNKNOWN and annotated.receipt["email_verified"] is True
        events = await store.application_events(row.id)
        assert events[-1]["event_type"] == "mail_oa_invite" and events[-1]["from_state"] == "SUBMISSION_UNKNOWN"
        assert await store.ambiguous_submits_since("greenhouse", since) == 1
        released = await store.transition(annotated, S.FAILED, OWNER_RELEASE_REASON)
        assert released.state == S.FAILED
        assert await store.ambiguous_submits_since("greenhouse", since) == 0, type(store).__name__
        assert await store.annotate_application("00000000-0000-0000-0000-000000000000"
                                                if isinstance(store, PostgresStore) else "nope", "x") is None


async def test_widened_mail_event_kinds_and_per_application_list(stores):
    pg = stores[0]
    row = await unknown_row(pg, 2)
    events = MailEventStore(pg.connection)
    assert await events.funnel_kinds_ready() is True
    for key, kind in (("c1", "CONFIRMATION"), ("o1", "OA_INVITE"), ("r1", "REJECTED")):
        assert await events.add(MailEvent(key, kind, "imap", "x@example.com", f"{kind} subject", None,
                                          datetime.now(UTC), application_id=row.id))
    linked = await events.for_application(row.id)
    assert {e.kind for e in linked} == {"CONFIRMATION", "OA_INVITE", "REJECTED"}
