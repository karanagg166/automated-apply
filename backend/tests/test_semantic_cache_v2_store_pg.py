"""Followup 006 on a disposable PostgreSQL: additive + idempotent DDL, and PostgresCacheStore (v2
mode) behaves exactly like MemoryCacheStore for metadata, prefilters, status, counters and purge."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import pytest_asyncio

from backend.app.ai_v2.semantic_cache import (
    CacheTelemetry,
    MemoryCacheStore,
    PostgresCacheStore,
    QuestionContext,
    SemanticCache,
    profile_version_hash,
)
from backend.app.browser_v2.answers import CandidateFacts
from backend.tests.test_ai_v2_semantic_cache import FAKE_PGVECTOR, semantic_cache_ddl
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

ROOT = Path(__file__).resolve().parents[2]
SQL_006 = (ROOT / "supabase/fresh_public/followups/006_semantic_cache_v2.sql").read_text()
KIND = "screening_qa"


class ConstantEmbedder:
    model_name, dimensions, ready = "constant", 384, True

    async def embed(self, text):
        return [1.0] + [0.0] * 383


def test_followup_006_is_additive_and_idempotent():
    code = re.sub(r"--.*", "", SQL_006).upper()
    for forbidden in ("DROP ", "TRUNCATE", "DELETE FROM", "ALTER COLUMN", "UPDATE PUBLIC"):
        assert forbidden not in code, forbidden
    assert code.count("ADD COLUMN IF NOT EXISTS") == 16
    assert not re.search(r"CREATE (?:UNIQUE )?INDEX (?!IF NOT EXISTS)", code)
    assert "IF NOT EXISTS (SELECT 1 FROM PG_CONSTRAINT" in code


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1":
        pytest.skip("local PostgreSQL binaries not available")
    tmp = tmp_path_factory.mktemp("pgcache006")
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
        subprocess.run([*psql, "-c", FAKE_PGVECTOR + semantic_cache_ddl()], check=True, capture_output=True)
        # A pre-006 row must survive the migration with safe defaults.
        subprocess.run([*psql, "-c", "INSERT INTO public.semantic_cache (kind, question_text, normalized_question, "
                        "answer_text, source) VALUES ('screening_qa', 'Legacy?', 'legacy', 'Yes', 'user')"],
                       check=True, capture_output=True)
        for _ in range(2):  # idempotent
            subprocess.run([*psql, "-c", SQL_006], check=True, capture_output=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest_asyncio.fixture
async def connection(database):
    import asyncpg

    conn = await asyncpg.connect(database)
    yield conn
    await conn.close()


async def test_legacy_row_gets_safe_defaults(connection):
    row = await connection.fetchrow("SELECT status, scope, human_override_count, entities::text AS e "
                                    "FROM public.semantic_cache WHERE normalized_question = 'legacy'")
    assert (row["status"], row["scope"], row["human_override_count"], row["e"]) == ("active", "global", 0, "{}")


async def scenario(cache: SemanticCache) -> dict:
    """One end-to-end script; run on both stores and compare the observable results."""
    facts = CandidateFacts(notice_period_days=30, expected_ctc="12")
    profile = profile_version_hash(facts)
    out: dict = {}
    stripe = await cache.put(KIND, "Why do you want to join Stripe?", "Payments infrastructure excites me.",
                             "user", context=QuestionContext(company="Stripe", field_kind="textarea"))
    out["scope"] = (stripe.entry.meta.scope, stripe.entry.meta.company_slug, stripe.entry.meta.invalidation_scope)
    out["razorpay"] = await cache.lookup(KIND, "Why do you want to join Razorpay?",
                                         context=QuestionContext(company="Razorpay", field_kind="textarea"))
    out["stripe"] = (await cache.lookup(KIND, "Why do you want to join Stripe?",
                                        context=QuestionContext(company="Stripe", field_kind="textarea"))).match
    notice = await cache.put(KIND, "What is your notice period in days?", "30 Days", "user",
                             context=QuestionContext(options=("Immediate", "15 Days", "30 Days"), profile_hash=profile))
    out["notice_meta"] = (notice.entry.meta.field_type, notice.entry.meta.intent_bucket,
                          notice.entry.meta.profile_version_hash == profile)
    out["option_mismatch"] = await cache.lookup(KIND, "What is your notice period in days?",
                                                context=QuestionContext(options=("Immediate", "60 Days"),
                                                                        profile_hash=profile))
    out["stale"] = await cache.lookup(KIND, "What is your notice period in days?",
                                      context=QuestionContext(options=("Immediate", "15 Days", "30 Days"),
                                                              profile_hash="0" * 64))
    out["fresh"] = (await cache.lookup(KIND, "What is your notice period in days?",
                                       context=QuestionContext(options=("Immediate", "15 Days", "30 Days"),
                                                               profile_hash=profile))).answer
    java = await cache.put(KIND, "Years of experience with Java?", "1", "user")
    out["javascript"] = await cache.lookup(KIND, "Years of experience with JavaScript?")
    bumped = await cache.record_form_validation_error(java.entry.id)
    out["quarantined"] = (bumped.status, bumped.form_validation_error_count, bumped.quarantine_reason)
    out["java_after"] = await cache.lookup(KIND, "Years of experience with Java?")
    out["counts"] = await cache.store.status_counts()
    listed, total = await cache.store.list_entries(None, None, 10, 0, status="quarantined")
    out["listed"] = (total, [e.id == java.entry.id for e in listed])
    out["purged"] = await cache.purge(status="quarantined")
    out["after_purge"] = await cache.store.status_counts()
    return out


async def test_postgres_v2_store_matches_memory(connection):
    await connection.execute("DELETE FROM public.semantic_cache WHERE kind = 'screening_qa'")
    store = PostgresCacheStore(connection)
    assert await store.metadata_ready()
    pg = await scenario(SemanticCache(store, ConstantEmbedder(), telemetry=CacheTelemetry()))
    memory = await scenario(SemanticCache(MemoryCacheStore(), ConstantEmbedder(), telemetry=CacheTelemetry()))
    assert pg == memory
    assert pg["scope"] == ("company", "stripe", "company_scoped") and pg["razorpay"] is None
    assert pg["notice_meta"] == ("single_select", "notice_period", True)
    assert pg["option_mismatch"] is None and pg["stale"] is None and pg["fresh"] == "30 Days"
    assert pg["javascript"] is None and pg["java_after"] is None
    assert pg["quarantined"] == ("quarantined", 1, "form_validation_error")
    assert pg["counts"]["quarantined"] == 1 and pg["listed"] == (1, [True]) and pg["purged"] == 1


async def test_legacy_mode_quarantine_deletes_the_row(database):
    import asyncpg

    conn = await asyncpg.connect(database)
    try:
        store = PostgresCacheStore(conn)
        store._v2 = False  # simulate code running before followup 006
        cache = SemanticCache(store, ConstantEmbedder(), telemetry=CacheTelemetry())
        put = await cache.put(KIND, "Are you open to night shifts?", "Yes", "user")
        entry = await cache.quarantine(put.entry.id, "owner")
        assert entry.status == "quarantined" and await store.get(put.entry.id) is None
    finally:
        await conn.close()
