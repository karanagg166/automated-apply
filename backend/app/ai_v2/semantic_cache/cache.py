"""SemanticCache facade: exact canonical lookup, then hard-prefiltered + guarded semantic lookup.

Lookup (screening kinds):
  1. exact   (kind, canonical storage key) -> guards (status, scope, stale profile, options):
             zero embedding calls
  2. vector  only after the SQL prefilters (status, intent, field type, company scope), every
             candidate re-checked by `guards.evaluate` (entities, polarity, cross-company, per-field
             thresholds, option fit) BEFORE it is counted as a hit; rejected candidates fall through
             to the next one.
Writes (poison-proofing): never_cache questions, company-scoped questions without a company,
work-authorization/sponsorship questions without a named country and LLM answers without an
approving judge verdict are refused. Exact-only kinds (JD scores) keep the plain behaviour and are
never embedded.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from backend.app.ai_v2.embeddings import Embedder
from backend.app.ai_v2.semantic_cache.guards import QueryProfile, build_query, evaluate
from backend.app.ai_v2.semantic_cache.keys import cache_key, options_hash, storage_key
from backend.app.ai_v2.semantic_cache.models import (
    DEFAULT_THRESHOLD,
    KIND_PATTERN,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    SOURCES,
    CacheEntry,
    EntryMeta,
    InvalidCacheEntry,
    Prefilter,
    PutResult,
    QuestionContext,
    normalize_question,
)
from backend.app.ai_v2.semantic_cache.policy import (
    GEO_INTENTS,
    CacheThresholds,
    compatible_field_types,
    ttl_for,
)
from backend.app.ai_v2.semantic_cache.telemetry import TELEMETRY, CacheTelemetry

# Same logger name as before the package split.
logger = logging.getLogger("backend.app.ai_v2.semantic_cache")
EXACT_ONLY_KINDS = frozenset({"jd_score"})
NEAREST_LIMIT = 8


@dataclass(frozen=True)
class CacheHit:
    entry: CacheEntry
    similarity: float
    match: str  # exact | semantic
    answer: str | None = None  # the cached value mapped onto the live options (None = no options given)


def write_refusal(query: QueryProfile) -> str | None:
    """Why a screening answer must not be written (None = cacheable)."""
    if query.policy == "never_cache":
        return "never_cache"
    if query.policy == "company_scoped" and not query.company_slug:
        return "company_unknown"
    if query.intent in GEO_INTENTS and not query.qualifiers.country:
        return "geo_unknown"
    return None


class SemanticCache:
    def __init__(self, store: Any, embedder: Embedder, *, threshold: float = DEFAULT_THRESHOLD,
                 thresholds: CacheThresholds | None = None, telemetry: CacheTelemetry | None = None) -> None:
        if not 0.5 <= threshold <= 1.0:
            raise ValueError("semantic cache threshold must be within [0.5, 1.0]")
        self.store = store
        self.embedder = embedder
        self.threshold = threshold
        self.thresholds = thresholds or CacheThresholds(long_text=threshold)
        self.telemetry = telemetry or TELEMETRY
        self.profile_hash: str | None = None  # last known candidate profile hash (set by the answerer)

    def configure(self, env: Any) -> None:
        """Per-field-type thresholds from env (SEMANTIC_CACHE_THRESHOLD_FACTUAL / _LONG_TEXT / ...)."""
        self.thresholds = CacheThresholds.from_env(env, long_text=self.threshold)

    async def _embed(self, normalized: str) -> list[float] | None:
        try:
            return await self.embedder.embed(normalized)
        except Exception as exc:  # noqa: BLE001 - embedding failure degrades to exact-only
            logger.warning("semantic_cache embed_failed model=%s error=%s", self.embedder.model_name,
                           type(exc).__name__)
            return None

    def _query(self, kind: str, question: str, context: QuestionContext | None) -> QueryProfile:
        if context is not None and context.profile_hash is None and self.profile_hash:
            context = replace(context, profile_hash=self.profile_hash)
        return build_query(kind, question, context)

    # --- lookup --------------------------------------------------------------------------
    async def lookup(self, kind: str, question: str, *, semantic: bool = True, threshold: float | None = None,
                     context: QuestionContext | None = None) -> CacheHit | None:
        if kind in EXACT_ONLY_KINDS:
            return await self._exact_only(kind, question)
        query = self._query(kind, question, context)
        if not query.canonical:
            return None
        if query.policy == "never_cache":
            self.telemetry.record("skipped_never_cache", kind=kind, intent=query.intent)
            return None
        hit = await self._find(query, semantic=semantic, threshold=threshold, record=True)
        if hit is not None:
            await self.store.record_hit(hit.entry.id)
            hit = replace(hit, entry=replace(hit.entry, hits=hit.entry.hits + 1))
            self.telemetry.record(f"{hit.match}_hit", kind=kind, intent=query.intent, id=hit.entry.id,
                                  similarity=f"{hit.similarity:.3f}")
        return hit

    async def explain(self, kind: str, question: str,
                      context: QuestionContext | None = None) -> tuple[QueryProfile, CacheHit | None]:
        """Dry-run lookup for the admin API: classification + the hit it WOULD serve (no hit counted)."""
        query = self._query(kind, question, context)
        if not query.canonical or query.policy == "never_cache":
            return query, None
        return query, await self._find(query, semantic=True, threshold=None, record=False)

    async def explain_candidates(self, query: QueryProfile, limit: int = 5) -> list[dict[str, Any]]:
        """Milestone 2 playground trace: every exact/nearest candidate with the guard decision it got
        (None = would be served). Read-only: no hit, no telemetry."""
        if not query.canonical or query.policy == "never_cache":
            return []
        base = self.threshold
        rows: list[tuple[CacheEntry, float, str]] = []
        seen: set[str] = set()
        for key in self._exact_keys(query):
            entry = await self.store.exact(query.kind, key)
            if entry is not None and entry.id not in seen:
                seen.add(entry.id)
                rows.append((entry, 1.0, "exact"))
        embedding = await self._embed(query.canonical)
        if embedding is not None:
            for candidate, similarity in await self.store.nearest(query.kind, embedding, 0.5, limit):
                if candidate.id not in seen:
                    seen.add(candidate.id)
                    rows.append((candidate, similarity, "semantic"))
        out: list[dict[str, Any]] = []
        for entry, similarity, match in rows[:limit]:
            decision, _ = evaluate(query, entry, similarity, thresholds=self.thresholds, base_threshold=base)
            out.append({"id": entry.id, "question": entry.question_text, "answer": entry.answer_text,
                        "match": match, "similarity": round(similarity, 4), "status": entry.status,
                        "decision": decision or "served"})
        return out

    async def _exact_only(self, kind: str, question: str) -> CacheHit | None:
        entry = await self.store.exact(kind, normalize_question(question))
        if entry is None or entry.status != "active":
            return None
        await self.store.record_hit(entry.id)
        return CacheHit(replace(entry, hits=entry.hits + 1), 1.0, "exact")

    def _exact_keys(self, query: QueryProfile) -> list[str]:
        keys = [storage_key(query.canonical, query.scope_slug)]
        legacy = normalize_question(query.question)
        if legacy and legacy not in keys:
            keys.append(legacy)
        return keys

    async def _find(self, query: QueryProfile, *, semantic: bool, threshold: float | None,
                    record: bool) -> CacheHit | None:
        base = threshold or self.threshold
        seen: set[str] = set()
        for key in self._exact_keys(query):
            entry = await self.store.exact(query.kind, key)
            if entry is None or entry.id in seen:
                continue
            seen.add(entry.id)
            decision, fitted = evaluate(query, entry, 1.0, thresholds=self.thresholds, base_threshold=base)
            if decision is None:
                return CacheHit(entry, 1.0, "exact", fitted if query.options else None)
            if record:
                self.telemetry.record(decision, kind=query.kind, id=entry.id, match="exact")
        if not semantic:
            return None
        embedding = await self._embed(query.canonical)
        if embedding is None:
            return None
        floor = self.thresholds.floor(query.field_type, query.intent) if query.typed else base
        prefilter = Prefilter(intent_bucket=query.intent,
                              field_types=tuple(sorted(compatible_field_types(query.field_type)))
                              if query.typed else (), company_slug=query.company_slug)
        candidates = await self.store.nearest(query.kind, embedding, max(0.5, floor - self.thresholds.band),
                                              NEAREST_LIMIT, prefilter=prefilter)
        for candidate, similarity in candidates:
            if candidate.id in seen:
                continue
            decision, fitted = evaluate(query, candidate, similarity, thresholds=self.thresholds,
                                        base_threshold=base)
            if decision is None:
                return CacheHit(candidate, similarity, "semantic", fitted if query.options else None)
            if record:
                self.telemetry.record(decision, kind=query.kind, id=candidate.id, similarity=f"{similarity:.3f}")
        return None

    # --- writes --------------------------------------------------------------------------
    def _meta(self, query: QueryProfile, answer_text: str, verified_by: str | None) -> EntryMeta:
        scope_slug = query.scope_slug
        factual = query.invalidation == "factual_profile"
        entities: dict[str, Any] = dict(query.qualifiers.entities())
        if query.company_slug:
            entities["company"] = query.company_slug
        # Unknown form context -> NULL type (the guard then only separates long-form from short values).
        field_type = query.field_type if query.typed else None
        ttl = ttl_for(query.invalidation)
        profile_hash = query.profile_hash if factual else None
        return EntryMeta(
            field_type=field_type, intent_bucket=query.intent, entities=entities,
            scope="company" if scope_slug else "global", company_slug=scope_slug, profile_version_hash=profile_hash,
            invalidation_scope=query.invalidation, expires_at=datetime.now(UTC) + ttl if ttl else None,
            verified_by=verified_by, options_hash=options_hash(query.options),
            cache_key=cache_key(intent=query.intent, field_type=field_type or "", canonical=query.canonical,
                                options=query.options, scope_slug=scope_slug, profile_hash=profile_hash))

    async def put(self, kind: str, question_text: str, answer_text: str, source: str, *,
                  context: QuestionContext | None = None, verified_by: str | None = None) -> PutResult:
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
        if kind in EXACT_ONLY_KINDS:  # JD scores: exact-only, never embedded (no HNSW pollution)
            return await self.store.upsert(kind, question_text, normalized, None, answer_text, source)
        query = self._query(kind, question_text, context or QuestionContext())
        query = replace(query, typed=context is not None)
        refusal = write_refusal(query)
        # The screening pipeline (which always passes a context) may only promote judge-approved LLM
        # answers; context-free low-level writes keep the plain source-precedence contract.
        if refusal is None and source == "llm" and context is not None \
                and not (verified_by or "").startswith("judge:"):
            refusal = "unverified_llm"
        if refusal is not None:
            self.telemetry.record("refused_unverified_llm" if refusal == "unverified_llm" else "refused_write",
                                  kind=kind, reason=refusal, intent=query.intent)
            raise InvalidCacheEntry(f"not cacheable: {refusal}")
        if verified_by is None and source == "user":
            verified_by = "human"
        meta = self._meta(query, answer_text, verified_by)
        embedding = await self._embed(query.canonical)
        result = await self.store.upsert(kind, question_text, storage_key(query.canonical, query.scope_slug),
                                         embedding, answer_text, source, meta=meta)
        if result.outcome != "kept_higher_priority":
            self.telemetry.record("promoted_human" if source == "user" else "promoted_llm_verified"
                                  if source == "llm" else "promoted_profile", kind=kind, intent=query.intent,
                                  id=result.entry.id)
        return result

    async def store_verified_user_answer(self, question: str, answer: str, kind: str = "screening_qa", *,
                                         context: QuestionContext | None = None) -> PutResult:
        """Telegram/dashboard HITL hook: a human-verified answer outranks every other source. A cached
        answer that the human contradicts is quarantined at once (never served again)."""
        query = self._query(kind, question, context or QuestionContext())
        previous = await self._find(replace(query, typed=context is not None), semantic=True, threshold=None,
                                    record=False)
        result = await self.put(kind, question, answer, "user", context=context)
        if previous is not None and previous.entry.id != result.entry.id \
                and normalize_question(previous.answer or previous.entry.answer_text) != normalize_question(answer):
            await self.record_human_override(previous.entry.id)
        elif previous is not None and previous.entry.id == result.entry.id \
                and normalize_question(previous.entry.answer_text) != normalize_question(answer):
            await self.store.bump(result.entry.id, "human_override_count")
        return result

    # --- quarantine / curation ---------------------------------------------------------------
    async def quarantine(self, entry_id: str, reason: str) -> CacheEntry | None:
        entry = await self.store.set_status(entry_id, "quarantined", reason)
        if entry is not None:
            self.telemetry.record("quarantined", id=entry_id, reason=reason)
        return entry

    async def unquarantine(self, entry_id: str) -> CacheEntry | None:
        return await self.store.set_status(entry_id, "active", None)

    async def record_human_override(self, entry_id: str) -> CacheEntry | None:
        """The owner answered differently from this cached entry: count it and quarantine it."""
        await self.store.bump(entry_id, "human_override_count")
        return await self.quarantine(entry_id, "human_override")

    async def record_form_validation_error(self, entry_id: str) -> CacheEntry | None:
        """A portal rejected the value this entry filled: count it and quarantine it immediately."""
        await self.store.bump(entry_id, "form_validation_error_count")
        return await self.quarantine(entry_id, "form_validation_error")

    async def purge(self, *, status: str | None = None, kind: str | None = None) -> int:
        return await self.store.purge(status=status, kind=kind)

    async def stats(self) -> dict[str, Any]:
        counts = await self.store.stats()
        try:
            statuses = await self.store.status_counts()
        except Exception:  # noqa: BLE001 - stats are best effort
            statuses = {}
        return counts | {"threshold": self.threshold, "thresholds": self.thresholds.__dict__,
                         "embedding_model": self.embedder.model_name, "embedding_dimensions": self.embedder.dimensions,
                         "embedding_ready": bool(self.embedder.ready), "backend": self.store.backend,
                         "status_counts": statuses, "decisions": self.telemetry.snapshot()}


async def seed_semantic_cache(cache: SemanticCache, reviewed_answers: Iterable[tuple[str, str]],
                              kind: str = "screening_qa") -> dict[str, int]:
    """Idempotently import reviewed application_answer_drafts (source='profile').

    Sensitive/blocked questions (passwords, IDs, consent, ...) and questions the cache refuses
    (cover letters, company motivation, country-less work authorization) are never cached."""
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
