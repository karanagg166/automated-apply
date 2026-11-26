"""Local semantic cache: exact normalized match first, then pgvector cosine >= threshold.

A high cosine score is not enough: "years of Python" vs "years of Java",
"current CTC" vs "expected CTC" and "relocate to Bengaluru" vs "relocate to
Hyderabad" embed almost identically. Every semantic candidate must also have
identical qualifiers (tech, current/expected, city, unit, numbers, negation,
work mode, employment type) or the hit is rejected.

Backends: `PostgresCacheStore` (public.semantic_cache, extensions.vector(384) +
HNSW cosine) and `MemoryCacheStore` (pure-Python cosine, same contract).

Package layout: `models` (limits, DTOs, store Protocol), `qualifiers` (entity-mismatch
guard), `stores` (memory + Postgres backends), `cache` (SemanticCache facade + seeding).
"""

from __future__ import annotations

from backend.app.ai_v2.semantic_cache.cache import (
    SemanticCache,
    logger,
    seed_semantic_cache,
)
from backend.app.ai_v2.semantic_cache.models import (
    DEFAULT_THRESHOLD,
    KIND_PATTERN,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    SOURCE_RANK,
    SOURCES,
    CacheEntry,
    CacheHit,
    CacheStore,
    InvalidCacheEntry,
    PutResult,
    normalize_question,
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

__all__ = [
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
