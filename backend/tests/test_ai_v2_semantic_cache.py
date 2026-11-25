"""Semantic cache: exact fast path, cosine threshold, entity-mismatch guard, upsert dedup,
source precedence, seeding, and the pgvector SQL against a disposable PostgreSQL."""

import os
import re
import shutil
import subprocess
import time

import pytest
import pytest_asyncio

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder, cosine
from backend.app.ai_v2.semantic_cache import (
    NEAREST_SQL,
    UPSERT_SQL,
    InvalidCacheEntry,
    MemoryCacheStore,
    PostgresCacheStore,
    SemanticCache,
    extract_qualifiers,
    normalize_question,
    qualifiers_conflict,
    seed_semantic_cache,
    vector_literal,
)
from backend.scripts.migrate_v2_core import MIGRATION
from backend.tests.test_v2_migration_sql import PG_BIN, free_port


class ConstantEmbedder:
    """Every text embeds identically (cosine 1.0): only the qualifier guard can reject a hit."""

    model_name = "constant"
    dimensions = 384
    ready = True

    async def embed(self, text):
        return [1.0] + [0.0] * 383


def cache(embedder=None, threshold=0.88):
    return SemanticCache(MemoryCacheStore(), embedder or DeterministicTestEmbedder(), threshold=threshold)


def test_normalization_keeps_cpp_and_csharp():
    assert normalize_question("  How many YEARS of C++ / C#?? ") == "how many years of c++ c#"
    assert extract_qualifiers("Years of experience in C++?").tech == {"c++"}


@pytest.mark.parametrize("left,right,field", [
    ("How many years of experience do you have in Python?", "How many years of experience do you have in Java?",
     "tech"),
    ("What is your current CTC?", "What is your expected CTC?", "temporal"),
    ("Are you willing to relocate to Bengaluru?", "Are you willing to relocate to Hyderabad?", "city"),
    ("Can you join within 15 days?", "Can you join within 30 days?", "number"),
    ("What is your expected CTC in lakhs?", "What is your expected CTC per month?", "unit"),
    ("Are you okay with a remote role?", "Are you okay with an onsite role?", "work_mode"),
    ("Are you open to a contract role?", "Are you open to a full time role?", "employment"),
    ("Do you have experience with React?", "Do you have experience with Angular?", "tech"),
    ("How many years of Go experience?", "How many years of experience?", "tech"),
])
def test_qualifier_conflicts_are_detected(left, right, field):
    assert field in qualifiers_conflict(left, right)


def test_equivalent_phrasings_do_not_conflict():
    assert qualifiers_conflict("Years of experience in ReactJS?", "How many years have you worked with React?") == []
    assert qualifiers_conflict("Willing to relocate to Bangalore?", "Are you ok relocating to Bengaluru?") == []
    assert qualifiers_conflict("Current CTC (LPA)?", "What is your present CTC in LPA?") == []
    assert extract_qualifiers("Are you willing to go to the office?").tech == frozenset()
    assert qualifiers_conflict("Work from office 5 days a week?", "Work from the office five days a week?") == []


async def test_exact_match_skips_embedding_and_counts_hits():
    embedder = DeterministicTestEmbedder()
    store = cache(embedder)
    await store.put("screening_qa", "Are you willing to work night shifts?", "No", "user")
    calls = embedder.calls
    hit = await store.lookup("screening_qa", "are you WILLING to work night-shifts")
    assert hit is not None and hit.match == "exact" and hit.similarity == 1.0
    assert embedder.calls == calls  # exact fast path: no embedding
    assert hit.entry.hits == 1 and (await store.stats())["total_hits"] == 1


async def test_semantic_hit_at_threshold_and_miss_below():
    store = cache()
    await store.put("screening_qa", "How many years of experience do you have with Docker containers?", "2", "user")
    query = "How many years of experience do you have with Docker containers in production?"
    vectors = [await store.embedder.embed(normalize_question(q)) for q in (
        query, "How many years of experience do you have with Docker containers?")]
    assert cosine(*vectors) >= 0.88
    hit = await store.lookup("screening_qa", query)
    assert hit is not None and hit.match == "semantic" and hit.entry.answer_text == "2"
    assert hit.entry.hits == 1
    assert await store.lookup("screening_qa", "Describe a difficult bug you fixed with Docker") is None
    assert await store.lookup("other_kind", query) is None  # kind filter


@pytest.mark.parametrize("cached,query", [
    ("How many years of experience do you have in Python?", "How many years of experience do you have in Java?"),
    ("What is your current CTC in lakhs per annum?", "What is your expected CTC in lakhs per annum?"),
    ("Are you willing to relocate to Bengaluru for this role?", "Are you willing to relocate to Hyderabad for this role?"),
])
async def test_entity_mismatch_guard_blocks_false_hits_even_at_cosine_one(cached, query):
    for embedder in (DeterministicTestEmbedder(), ConstantEmbedder()):
        store = cache(embedder)
        await store.put("screening_qa", cached, "5", "user")
        assert await store.lookup("screening_qa", query) is None
        rows, _ = await store.store.list_entries(None, None, 10, 0)
        assert rows[0].hits == 0  # rejected candidates never count as hits


async def test_deterministic_embedder_scores_python_java_above_threshold():
    """The guard, not the threshold, is what stops the classic Python/Java false hit."""
    embedder = DeterministicTestEmbedder()
    a = await embedder.embed(normalize_question("How many years of experience do you have in Python?"))
    b = await embedder.embed(normalize_question("How many years of experience do you have in Java?"))
    assert cosine(a, b) >= 0.88


async def test_upsert_dedups_and_respects_source_precedence():
    store = cache()
    first = await store.put("screening_qa", "Notice period?", "30 days", "llm")
    assert first.outcome == "inserted"
    second = await store.put("screening_qa", "notice  period", "15 days", "user")
    assert second.outcome == "updated" and second.entry.id == first.entry.id
    kept = await store.put("screening_qa", "Notice period", "60 days", "llm")
    assert kept.outcome == "kept_higher_priority" and kept.entry.answer_text == "15 days"
    assert (await store.stats())["total_entries"] == 1


async def test_put_validation_and_user_answer_hook():
    store = cache()
    with pytest.raises(InvalidCacheEntry):
        await store.put("screening_qa", "???", "x", "user")
    with pytest.raises(InvalidCacheEntry):
        await store.put("screening_qa", "Question", "x", "robot")
    with pytest.raises(InvalidCacheEntry):
        await store.put("Bad Kind", "Question", "x", "user")
    result = await store.store_verified_user_answer("Do you hold a valid passport?", "Yes")
    assert result.entry.source == "user"


async def test_embedding_failure_degrades_to_exact_only():
    class Broken:
        model_name, dimensions, ready = "broken", 384, False

        async def embed(self, text):
            raise RuntimeError("model download failed")

    store = SemanticCache(MemoryCacheStore(), Broken())
    await store.put("screening_qa", "Are you an immediate joiner?", "No", "user")
    assert (await store.lookup("screening_qa", "Are you an immediate joiner?")).match == "exact"
    assert await store.lookup("screening_qa", "Can you join immediately?") is None


async def test_seed_is_idempotent_and_skips_sensitive_questions():
    store = cache()
    reviewed = [("Are you willing to work in rotational shifts?", "Yes"),
                ("What is your PAN number?", "ABCDE1234F"),
                ("Enter your password", "x"), ("", "y"), ("Why this company?", "")]
    first = await seed_semantic_cache(store, reviewed)
    assert first == {"seen": 5, "inserted": 1, "updated": 0, "kept_higher_priority": 0, "skipped": 4}
    second = await seed_semantic_cache(store, reviewed)
    assert second["inserted"] == 0 and second["updated"] == 1
    await store.store_verified_user_answer("Are you willing to work in rotational shifts?", "No")
    third = await seed_semantic_cache(store, reviewed)
    assert third["kept_higher_priority"] == 1
    assert (await store.stats())["total_entries"] == 1


def test_pgvector_sql_shape():
    assert "OPERATOR(extensions.<=>)" in NEAREST_SQL and "$2::text::extensions.vector" in NEAREST_SQL
    assert ">= $3" in NEAREST_SQL and "kind = $1" in NEAREST_SQL and "LIMIT $4" in NEAREST_SQL
    assert "ORDER BY embedding OPERATOR(extensions.<=>)" in NEAREST_SQL  # HNSW-indexable ordering
    assert "ON CONFLICT (kind, normalized_question) DO UPDATE" in UPSERT_SQL
    assert vector_literal([0.5, -0.25, 1.0]) == "[0.5,-0.25,1]"
    sql = MIGRATION.read_text()
    assert "embedding extensions.vector(384)" in sql
    assert "USING hnsw (embedding extensions.vector_cosine_ops)" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I" in sql and "deletable" in sql


# --- real SQL on a disposable PostgreSQL ------------------------------------------------
# pgvector is not installed locally, so `extensions.vector` is emulated with a text domain
# and a SQL cosine-distance operator. Everything else is the real migration DDL + store SQL.
FAKE_PGVECTOR = """
CREATE SCHEMA extensions;
CREATE DOMAIN extensions.vector AS text;
CREATE FUNCTION extensions.fake_cosine_distance(a text, b text) RETURNS float8
LANGUAGE sql IMMUTABLE AS $$
  SELECT 1 - sum(x * y) / (sqrt(sum(x * x)) * sqrt(sum(y * y)))
  FROM unnest(string_to_array(trim(both '[]' from a), ',')::float8[],
              string_to_array(trim(both '[]' from b), ',')::float8[]) AS t(x, y) $$;
CREATE OPERATOR extensions.<=> (LEFTARG = text, RIGHTARG = text, FUNCTION = extensions.fake_cosine_distance);
"""


def semantic_cache_ddl():
    blocks = re.findall(r"-- BEGIN pgvector\n(.*?)-- END pgvector\n", MIGRATION.read_text(), re.DOTALL)
    block = next(b for b in blocks if "public.semantic_cache" in b)
    block = re.sub(r"CREATE EXTENSION[^;]*;", "", block)
    block = re.sub(r"CREATE INDEX IF NOT EXISTS ix_semantic_cache_embedding_hnsw.*?;", "", block, flags=re.DOTALL)
    return block.replace("extensions.vector(384)", "extensions.vector")


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1":
        pytest.skip("local PostgreSQL binaries not available")
    tmp = tmp_path_factory.mktemp("pgcache")
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
        subprocess.run([*psql, "-c", FAKE_PGVECTOR + semantic_cache_ddl()], check=True, capture_output=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest_asyncio.fixture
async def pg_cache(database):
    import asyncpg

    connection = await asyncpg.connect(database)
    await connection.execute("TRUNCATE public.semantic_cache")
    assert await PostgresCacheStore.ready(connection)
    yield SemanticCache(PostgresCacheStore(connection), DeterministicTestEmbedder())
    await connection.close()


async def test_postgres_store_matches_memory_semantics(pg_cache):
    first = await pg_cache.put("screening_qa", "How many years of experience do you have with Docker containers?",
                               "2", "profile")
    assert first.outcome == "inserted"
    assert (await pg_cache.put("screening_qa", "how many years of experience do you have with docker containers",
                               "3", "user")).outcome == "updated"
    assert (await pg_cache.put("screening_qa", "How many years of experience do you have with Docker containers",
                               "9", "llm")).outcome == "kept_higher_priority"
    exact = await pg_cache.lookup("screening_qa", "How many years of experience do you have with Docker containers?")
    assert exact.match == "exact" and exact.entry.answer_text == "3"
    semantic = await pg_cache.lookup(
        "screening_qa", "How many years of experience do you have with Docker containers in production?")
    assert semantic is not None and semantic.match == "semantic" and semantic.similarity >= 0.88
    await pg_cache.put("screening_qa", "How many years of experience do you have in Python?", "2", "user")
    assert await pg_cache.lookup("screening_qa", "How many years of experience do you have in Java?") is None
    stats = await pg_cache.store.stats()
    assert stats == {"total_entries": 2, "total_hits": 2}
    rows, total = await pg_cache.store.list_entries("screening_qa", "docker", 10, 0)
    assert total == 1 and rows[0].hits == 2 and rows[0].source == "user"
    assert await pg_cache.store.delete(rows[0].id) is True
    assert await pg_cache.store.delete(rows[0].id) is False
    assert (await pg_cache.store.stats())["total_entries"] == 1
