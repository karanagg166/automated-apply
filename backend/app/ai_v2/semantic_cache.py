"""Local semantic cache: exact normalized match first, then pgvector cosine >= threshold.

A high cosine score is not enough: "years of Python" vs "years of Java",
"current CTC" vs "expected CTC" and "relocate to Bengaluru" vs "relocate to
Hyderabad" embed almost identically. Every semantic candidate must also have
identical qualifiers (tech, current/expected, city, unit, numbers, negation,
work mode, employment type) or the hit is rejected.

Backends: `PostgresCacheStore` (public.semantic_cache, extensions.vector(384) +
HNSW cosine) and `MemoryCacheStore` (pure-Python cosine, same contract).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.app.ai_v2.embeddings import Embedder, cosine
from backend.app.browser_v2.tech_terms import phrase_terms, tech_terms

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.88
SOURCES = ("user", "profile", "llm")
# A verified human answer is never overwritten by a profile seed or an LLM answer.
SOURCE_RANK = {"llm": 1, "profile": 2, "user": 3}
KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_QUESTION_CHARS = 1000
MAX_ANSWER_CHARS = 4000


class InvalidCacheEntry(ValueError):
    pass


def normalize_question(text: str) -> str:
    """Lowercase, strip punctuation (keeping + and # for C++/C#), collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", (text or "").lower())).strip()


# --- qualifier extraction (entity-mismatch guard) -------------------------------------
_CITY_ALIASES = {
    "bangalore": "bengaluru", "bombay": "mumbai", "gurugram": "gurgaon", "madras": "chennai",
    "calcutta": "kolkata", "new delhi": "delhi", "trivandrum": "thiruvananthapuram",
    "poona": "pune", "noida extension": "noida", "navi mumbai": "navi mumbai", "ncr": "delhi ncr",
    "delhi ncr": "delhi ncr", "sf": "san francisco", "nyc": "new york",
}
_CITIES = frozenset({
    "bengaluru", "mumbai", "delhi", "delhi ncr", "gurgaon", "noida", "hyderabad", "chennai", "kolkata",
    "pune", "ahmedabad", "jaipur", "chandigarh", "kochi", "thiruvananthapuram", "indore", "bhopal",
    "lucknow", "nagpur", "coimbatore", "mysuru", "mysore", "vadodara", "surat", "visakhapatnam",
    "bhubaneswar", "goa", "mohali", "dehradun", "navi mumbai", "thane", "faridabad", "ghaziabad",
    "london", "berlin", "singapore", "dubai", "new york", "san francisco", "seattle", "toronto",
    "amsterdam", "dublin", "sydney", "tokyo",
})
_TEMPORAL = {
    "current": re.compile(r"\b(?:current(?:ly)?|present|existing|now|today)\b"),
    "expected": re.compile(r"\b(?:expected|expecting|expectation|desired|target|asking)\b"),
    "previous": re.compile(r"\b(?:previous|last|prior|former)\b"),
}
_UNITS = {
    "lakh": re.compile(r"\b(?:lakhs?|lacs?|lpa|l p a)\b"),
    "inr": re.compile(r"\b(?:inr|rupees?|rs)\b|₹"),
    "usd": re.compile(r"\b(?:usd|dollars?)\b|\$"),
    "monthly": re.compile(r"\b(?:per month|monthly|a month|pm)\b"),
    "annual": re.compile(r"\b(?:per annum|annual(?:ly)?|yearly|per year|pa)\b"),
    "hourly": re.compile(r"\b(?:per hour|hourly)\b"),
    "days": re.compile(r"\bdays?\b"),
    "weeks": re.compile(r"\bweeks?\b"),
    "months": re.compile(r"\bmonths?\b"),
}
_WORK_MODE = {
    "remote": re.compile(r"\b(?:remote(?:ly)?|work from home|wfh)\b"),
    "hybrid": re.compile(r"\bhybrid\b"),
    "onsite": re.compile(r"\b(?:on ?site|in office|office|work from office|wfo)\b"),
}
_EMPLOYMENT = {
    "full_time": re.compile(r"\bfull ?time\b"),
    "part_time": re.compile(r"\bpart ?time\b"),
    "contract": re.compile(r"\b(?:contract(?:ual)?|freelance|c2h)\b"),
    "internship": re.compile(r"\b(?:intern(?:ship)?)\b"),
    "night_shift": re.compile(r"\bnight shifts?\b"),
}
_NEGATION = re.compile(r"\b(?:not|never|no|without|n t|cannot|can t|don t|won t)\b")


@dataclass(frozen=True)
class Qualifiers:
    tech: frozenset[str] = frozenset()
    temporal: frozenset[str] = frozenset()
    city: frozenset[str] = frozenset()
    unit: frozenset[str] = frozenset()
    number: frozenset[str] = frozenset()
    negation: bool = False
    work_mode: frozenset[str] = frozenset()
    employment: frozenset[str] = frozenset()

    def differences(self, other: Qualifiers) -> list[str]:
        names = ("tech", "temporal", "city", "unit", "number", "negation", "work_mode", "employment")
        return [name for name in names if getattr(self, name) != getattr(other, name)]


_NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
                 "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40", "forty five": "45",
                 "sixty": "60", "ninety": "90"}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b")


def extract_qualifiers(question: str) -> Qualifiers:
    text = _NUMBER_WORD.sub(lambda m: _NUMBER_WORDS[m.group(1)], normalize_question(question))
    numbers = frozenset(re.findall(r"(?<![a-z])\d+(?:\.\d+)?", text))
    return Qualifiers(
        tech=tech_terms(text),
        temporal=frozenset(k for k, p in _TEMPORAL.items() if p.search(text)),
        city=phrase_terms(text, _CITIES, _CITY_ALIASES),
        unit=frozenset(k for k, p in _UNITS.items() if p.search(text)),
        number=numbers,
        negation=bool(_NEGATION.search(text)),
        work_mode=frozenset(k for k, p in _WORK_MODE.items() if p.search(text)),
        employment=frozenset(k for k, p in _EMPLOYMENT.items() if p.search(text)),
    )


def qualifiers_conflict(query: str | Qualifiers, cached: str | Qualifiers) -> list[str]:
    """Qualifier categories that differ (empty list = compatible)."""
    left = query if isinstance(query, Qualifiers) else extract_qualifiers(query)
    right = cached if isinstance(cached, Qualifiers) else extract_qualifiers(cached)
    return left.differences(right)


# --- storage ----------------------------------------------------------------------------
@dataclass(frozen=True)
class CacheEntry:
    id: str
    kind: str
    question_text: str
    normalized_question: str
    answer_text: str
    source: str
    hits: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "question_text": self.question_text,
                "answer_text": self.answer_text, "source": self.source, "hits": self.hits,
                "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass(frozen=True)
class CacheHit:
    entry: CacheEntry
    similarity: float
    match: str  # exact | semantic


@dataclass(frozen=True)
class PutResult:
    entry: CacheEntry
    outcome: str  # inserted | updated | kept_higher_priority


class CacheStore(Protocol):
    backend: str

    async def exact(self, kind: str, normalized: str) -> CacheEntry | None: ...

    async def nearest(self, kind: str, embedding: list[float], threshold: float,
                      limit: int = 5) -> list[tuple[CacheEntry, float]]: ...

    async def upsert(self, kind: str, question_text: str, normalized: str, embedding: list[float] | None,
                     answer_text: str, source: str) -> PutResult: ...

    async def record_hit(self, entry_id: str) -> None: ...

    async def list_entries(self, kind: str | None, query: str | None, limit: int,
                           offset: int) -> tuple[list[CacheEntry], int]: ...

    async def delete(self, entry_id: str) -> bool: ...

    async def stats(self) -> dict[str, int]: ...


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _MemoryRow:
    entry: CacheEntry
    embedding: list[float] | None = field(default=None)


class MemoryCacheStore:
    """Pure-Python parity backend for tests and `--dry-run --once` before migration 004."""

    backend = "memory"

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _MemoryRow] = {}

    async def exact(self, kind, normalized):
        row = self.rows.get((kind, normalized))
        return row.entry if row else None

    async def nearest(self, kind, embedding, threshold, limit=5):
        scored = [(row.entry, cosine(embedding, row.embedding)) for (k, _), row in self.rows.items()
                  if k == kind and row.embedding is not None]
        scored = [(e, s) for e, s in scored if s >= threshold]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]

    async def upsert(self, kind, question_text, normalized, embedding, answer_text, source):
        key, now = (kind, normalized), _now()
        current = self.rows.get(key)
        if current is None:
            entry = CacheEntry(id=str(uuid.uuid4()), kind=kind, question_text=question_text,
                               normalized_question=normalized, answer_text=answer_text, source=source,
                               created_at=now, updated_at=now)
            self.rows[key] = _MemoryRow(entry, embedding)
            return PutResult(entry, "inserted")
        if SOURCE_RANK[source] < SOURCE_RANK[current.entry.source]:
            return PutResult(current.entry, "kept_higher_priority")
        entry = replace(current.entry, question_text=question_text, answer_text=answer_text, source=source,
                        updated_at=now)
        self.rows[key] = _MemoryRow(entry, embedding if embedding is not None else current.embedding)
        return PutResult(entry, "updated")

    async def record_hit(self, entry_id):
        for key, row in self.rows.items():
            if row.entry.id == entry_id:
                self.rows[key] = _MemoryRow(replace(row.entry, hits=row.entry.hits + 1, updated_at=_now()),
                                            row.embedding)
                return

    async def list_entries(self, kind, query, limit, offset):
        needle = normalize_question(query or "")
        rows = [r.entry for r in self.rows.values() if (kind is None or r.entry.kind == kind)
                and (not needle or needle in r.entry.normalized_question
                     or needle in normalize_question(r.entry.answer_text))]
        rows.sort(key=lambda e: e.updated_at or _now(), reverse=True)
        return rows[offset:offset + limit], len(rows)

    async def delete(self, entry_id):
        for key, row in list(self.rows.items()):
            if row.entry.id == entry_id:
                del self.rows[key]
                return True
        return False

    async def stats(self):
        return {"total_entries": len(self.rows), "total_hits": sum(r.entry.hits for r in self.rows.values())}


def vector_literal(embedding: list[float]) -> str:
    """pgvector text input format: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.7g}" for x in embedding) + "]"


_ENTRY_COLUMNS = ("id::text AS id, kind, question_text, normalized_question, answer_text, source, hits, "
                  "created_at, updated_at")
# OPERATOR(extensions.<=>) resolves pgvector's cosine-distance operator without relying on
# search_path (the extension lives in schema `extensions` on Supabase).
NEAREST_SQL = (
    f"SELECT {_ENTRY_COLUMNS}, 1 - (embedding OPERATOR(extensions.<=>) $2::text::extensions.vector) AS similarity "
    "FROM public.semantic_cache WHERE kind = $1 AND embedding IS NOT NULL "
    "AND 1 - (embedding OPERATOR(extensions.<=>) $2::text::extensions.vector) >= $3 "
    "ORDER BY embedding OPERATOR(extensions.<=>) $2::text::extensions.vector LIMIT $4")
UPSERT_SQL = (
    "INSERT INTO public.semantic_cache (kind, question_text, normalized_question, embedding, answer_text, source) "
    "VALUES ($1, $2, $3, $4::text::extensions.vector, $5, $6) "
    "ON CONFLICT (kind, normalized_question) DO UPDATE SET "
    "question_text = EXCLUDED.question_text, answer_text = EXCLUDED.answer_text, source = EXCLUDED.source, "
    "embedding = COALESCE(EXCLUDED.embedding, public.semantic_cache.embedding), updated_at = now() "
    "WHERE (CASE EXCLUDED.source WHEN 'user' THEN 3 WHEN 'profile' THEN 2 ELSE 1 END) >= "
    "(CASE public.semantic_cache.source WHEN 'user' THEN 3 WHEN 'profile' THEN 2 ELSE 1 END) "
    f"RETURNING {_ENTRY_COLUMNS}, (xmax = 0) AS inserted")


def _entry(row: Any) -> CacheEntry:
    return CacheEntry(id=row["id"], kind=row["kind"], question_text=row["question_text"],
                      normalized_question=row["normalized_question"], answer_text=row["answer_text"],
                      source=row["source"], hits=row["hits"], created_at=row["created_at"],
                      updated_at=row["updated_at"])


class PostgresCacheStore:
    """public.semantic_cache over one asyncpg connection (shared with the v2 store)."""

    backend = "postgres"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    async def ready(connection: Any) -> bool:
        return bool(await connection.fetchval("SELECT to_regclass('public.semantic_cache') IS NOT NULL"))

    async def exact(self, kind, normalized):
        row = await self.connection.fetchrow(
            f"SELECT {_ENTRY_COLUMNS} FROM public.semantic_cache WHERE kind=$1 AND normalized_question=$2",
            kind, normalized)
        return _entry(row) if row else None

    async def nearest(self, kind, embedding, threshold, limit=5):
        rows = await self.connection.fetch(NEAREST_SQL, kind, vector_literal(embedding), threshold, limit)
        return [(_entry(row), float(row["similarity"])) for row in rows]

    async def upsert(self, kind, question_text, normalized, embedding, answer_text, source):
        row = await self.connection.fetchrow(
            UPSERT_SQL, kind, question_text, normalized,
            vector_literal(embedding) if embedding is not None else None, answer_text, source)
        if row is None:
            existing = await self.exact(kind, normalized)
            assert existing is not None
            return PutResult(existing, "kept_higher_priority")
        return PutResult(_entry(row), "inserted" if row["inserted"] else "updated")

    async def record_hit(self, entry_id):
        await self.connection.execute(
            "UPDATE public.semantic_cache SET hits = hits + 1, updated_at = now() WHERE id = $1::uuid", entry_id)

    async def list_entries(self, kind, query, limit, offset):
        needle = normalize_question(query or "")
        where, args = ["($1::text IS NULL OR kind = $1)"], [kind]
        if needle:
            args.append(f"%{needle}%")
            where.append("(normalized_question LIKE $2 OR lower(answer_text) LIKE $2)")
        clause = " AND ".join(where)
        total = await self.connection.fetchval(f"SELECT count(*) FROM public.semantic_cache WHERE {clause}", *args)
        rows = await self.connection.fetch(
            f"SELECT {_ENTRY_COLUMNS} FROM public.semantic_cache WHERE {clause} "
            f"ORDER BY updated_at DESC, id LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}", *args, limit, offset)
        return [_entry(row) for row in rows], int(total or 0)

    async def delete(self, entry_id):
        result = await self.connection.execute("DELETE FROM public.semantic_cache WHERE id = $1::uuid", entry_id)
        return str(result).endswith(" 1")

    async def stats(self):
        row = await self.connection.fetchrow(
            "SELECT count(*) AS total_entries, COALESCE(sum(hits), 0) AS total_hits FROM public.semantic_cache")
        return {"total_entries": int(row["total_entries"]), "total_hits": int(row["total_hits"])}


# --- facade ---------------------------------------------------------------------------
class SemanticCache:
    def __init__(self, store: CacheStore, embedder: Embedder, *, threshold: float = DEFAULT_THRESHOLD) -> None:
        if not 0.5 <= threshold <= 1.0:
            raise ValueError("semantic cache threshold must be within [0.5, 1.0]")
        self.store = store
        self.embedder = embedder
        self.threshold = threshold

    async def _embed(self, normalized: str) -> list[float] | None:
        try:
            return await self.embedder.embed(normalized)
        except Exception as exc:  # noqa: BLE001 - embedding failure degrades to exact-only
            logger.warning("semantic_cache embed_failed model=%s error=%s", self.embedder.model_name,
                           type(exc).__name__)
            return None

    async def lookup(self, kind: str, question: str, *, semantic: bool = True,
                     threshold: float | None = None) -> CacheHit | None:
        normalized = normalize_question(question)
        if not normalized:
            return None
        entry = await self.store.exact(kind, normalized)
        if entry is not None:
            await self.store.record_hit(entry.id)
            return CacheHit(replace(entry, hits=entry.hits + 1), 1.0, "exact")
        if not semantic:
            return None
        embedding = await self._embed(normalized)
        if embedding is None:
            return None
        wanted = extract_qualifiers(question)
        for candidate, similarity in await self.store.nearest(kind, embedding, threshold or self.threshold):
            conflicts = qualifiers_conflict(wanted, candidate.question_text)
            if conflicts:
                logger.info("semantic_cache qualifier_mismatch kind=%s similarity=%.3f fields=%s", kind,
                            similarity, ",".join(conflicts))
                continue
            await self.store.record_hit(candidate.id)
            return CacheHit(replace(candidate, hits=candidate.hits + 1), similarity, "semantic")
        return None

    async def put(self, kind: str, question_text: str, answer_text: str, source: str) -> PutResult:
        if not KIND_PATTERN.match(kind or ""):
            raise InvalidCacheEntry("invalid kind")
        if source not in SOURCES:
            raise InvalidCacheEntry("source must be user, profile or llm")
        question_text, answer_text = (question_text or "").strip(), (answer_text or "").strip()
        normalized = normalize_question(question_text)
        if not normalized or not answer_text:
            raise InvalidCacheEntry("question and answer are required")
        if len(question_text) > MAX_QUESTION_CHARS or len(answer_text) > MAX_ANSWER_CHARS:
            raise InvalidCacheEntry("question or answer too long")
        embedding = await self._embed(normalized)
        return await self.store.upsert(kind, question_text, normalized, embedding, answer_text, source)

    async def store_verified_user_answer(self, question: str, answer: str,
                                         kind: str = "screening_qa") -> PutResult:
        """Phase 4 Telegram HITL hook: a human-verified answer outranks every other source."""
        return await self.put(kind, question, answer, "user")

    async def stats(self) -> dict[str, Any]:
        counts = await self.store.stats()
        return counts | {"threshold": self.threshold, "embedding_model": self.embedder.model_name,
                         "embedding_dimensions": self.embedder.dimensions,
                         "embedding_ready": bool(self.embedder.ready), "backend": self.store.backend}


async def seed_semantic_cache(cache: SemanticCache, reviewed_answers: Iterable[tuple[str, str]],
                              kind: str = "screening_qa") -> dict[str, int]:
    """Idempotently import reviewed application_answer_drafts (source='profile').

    Sensitive/blocked questions (passwords, IDs, consent, ...) are never cached."""
    from backend.app.browser_v2.answers import BLOCKED, SENSITIVE

    counts = {"seen": 0, "inserted": 0, "updated": 0, "kept_higher_priority": 0, "skipped": 0}
    for question, answer in reviewed_answers:
        counts["seen"] += 1
        if not normalize_question(question or "") or not (answer or "").strip() \
                or BLOCKED.search(question) or SENSITIVE.search(question):
            counts["skipped"] += 1
            continue
        try:
            result = await cache.put(kind, question, answer, "profile")
        except InvalidCacheEntry:
            counts["skipped"] += 1
            continue
        counts[result.outcome] += 1
    return counts
