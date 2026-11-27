"""Local semantic cache: exact normalized match first, then pgvector cosine >= threshold.

A high cosine score is not enough: "years of Python" vs "years of Java",
"current CTC" vs "expected CTC" and "relocate to Bengaluru" vs "relocate to
Hyderabad" embed almost identically. Every semantic candidate must also have
identical qualifiers (tech, current/expected, city, unit, numbers, negation,
work mode, employment type) or the hit is rejected.

Backends: `PostgresCacheStore` (public.semantic_cache, extensions.vector(384) +
HNSW cosine) and `MemoryCacheStore` (pure-Python cosine, same contract).

Phase 4 (2026-11-28, poison-proof): intent buckets, field types, company scope, polarity and
country guards, per-field-type thresholds, profile-version invalidation, quarantine, verified-only
promotion and decision telemetry.

Package layout: `models` (limits, DTOs, store Protocol), `policy` (intent / field type / scope /
thresholds), `keys` (canonical text, cache key, profile hash), `qualifiers` (entity + polarity
extraction), `guards` (candidate acceptance), `telemetry` (decision counters), `stores` +
`stores_pg` (memory + Postgres backends), `cache` (SemanticCache facade + seeding).
"""

from __future__ import annotations

from backend.app.ai_v2.semantic_cache.cache import (
    EXACT_ONLY_KINDS,
    CacheHit,
    SemanticCache,
    logger,
    seed_semantic_cache,
    write_refusal,
)
from backend.app.ai_v2.semantic_cache.guards import (
    QueryProfile,
    build_query,
    evaluate,
    fit_answer,
)
from backend.app.ai_v2.semantic_cache.keys import (
    canonical_question,
    company_slug,
    profile_hash_from_profile,
    profile_version_hash,
)
from backend.app.ai_v2.semantic_cache.models import (
    DEFAULT_THRESHOLD,
    KIND_PATTERN,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    SOURCE_RANK,
    SOURCES,
    CacheEntry,
    CacheStore,
    EntryMeta,
    InvalidCacheEntry,
    Prefilter,
    PutResult,
    QuestionContext,
    normalize_question,
)
from backend.app.ai_v2.semantic_cache.policy import (
    INTENTS,
    CacheThresholds,
    cache_policy,
    classify_intent,
    infer_field_type,
)
from backend.app.ai_v2.semantic_cache.qualifiers import (
    _CITIES,
    _CITY_ALIASES,
    _EMPLOYMENT,
    _NEGATION,
    _NUMBER_WORD,
    _NUMBER_WORDS,
    _TEMPORAL,
    _UNITS,
    _WORK_MODE,
    Qualifiers,
    extract_qualifiers,
    qualifiers_conflict,
)
from backend.app.ai_v2.semantic_cache.stores import (
    _ENTRY_COLUMNS,
    NEAREST_SQL,
    UPSERT_SQL,
    MemoryCacheStore,
    PostgresCacheStore,
    _entry,
    _MemoryRow,
    _now,
    vector_literal,
)
from backend.app.ai_v2.semantic_cache.telemetry import (
    TELEMETRY,
    CacheTelemetry,
    cache_decision_stats,
)

__all__ = [
    "EXACT_ONLY_KINDS",
    "INTENTS",
    "TELEMETRY",
    "CacheTelemetry",
    "CacheThresholds",
    "EntryMeta",
    "Prefilter",
    "QueryProfile",
    "QuestionContext",
    "build_query",
    "cache_decision_stats",
    "cache_policy",
    "canonical_question",
    "classify_intent",
    "company_slug",
    "evaluate",
    "fit_answer",
    "infer_field_type",
    "profile_hash_from_profile",
    "profile_version_hash",
    "write_refusal",
    "DEFAULT_THRESHOLD",
    "KIND_PATTERN",
    "MAX_ANSWER_CHARS",
    "MAX_QUESTION_CHARS",
    "NEAREST_SQL",
    "SOURCES",
    "SOURCE_RANK",
    "UPSERT_SQL",
    "_CITIES",
    "_CITY_ALIASES",
    "_EMPLOYMENT",
    "_ENTRY_COLUMNS",
    "_NEGATION",
    "_NUMBER_WORD",
    "_NUMBER_WORDS",
    "_TEMPORAL",
    "_UNITS",
    "_WORK_MODE",
    "CacheEntry",
    "CacheHit",
    "CacheStore",
    "InvalidCacheEntry",
    "MemoryCacheStore",
    "PostgresCacheStore",
    "PutResult",
    "Qualifiers",
    "SemanticCache",
    "_MemoryRow",
    "_entry",
    "_now",
    "extract_qualifiers",
    "logger",
    "normalize_question",
    "qualifiers_conflict",
    "seed_semantic_cache",
    "vector_literal",
]
