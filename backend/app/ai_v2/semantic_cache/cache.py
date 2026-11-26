"""SemanticCache facade (exact match, then qualifier-guarded semantic match) and seeding."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from backend.app.ai_v2.embeddings import Embedder
from backend.app.ai_v2.semantic_cache.models import (
    DEFAULT_THRESHOLD,
    KIND_PATTERN,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    SOURCES,
    CacheHit,
    CacheStore,
    InvalidCacheEntry,
    PutResult,
    normalize_question,
)
from backend.app.ai_v2.semantic_cache.qualifiers import (
    extract_qualifiers,
    qualifiers_conflict,
)

# Same logger name as before the package split.
logger = logging.getLogger("backend.app.ai_v2.semantic_cache")


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
