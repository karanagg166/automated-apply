"""Semantic-cache backends: MemoryCacheStore (tests, dry runs) and PostgresCacheStore (pgvector).

PostgresCacheStore lives in `stores_pg` and is re-exported here; both implement the same
`CacheStore` contract (prefiltered nearest, metadata-aware upsert, status/counters, purge).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from backend.app.ai_v2.embeddings import cosine
from backend.app.ai_v2.semantic_cache.models import (
    COUNTERS,
    SOURCE_RANK,
    CacheEntry,
    EntryMeta,
    Prefilter,
    PutResult,
    normalize_question,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _MemoryRow:
    entry: CacheEntry
    embedding: list[float] | None = field(default=None)


def passes_prefilter(entry: CacheEntry, prefilter: Prefilter | None) -> bool:
    """Same predicate as the Postgres WHERE clause (NULL metadata = legacy row, kept for Python guards)."""
    if entry.status != "active":
        return False
    if entry.meta.expires_at is not None and entry.meta.expires_at <= _now():
        return False
    if prefilter is None:
        return True
    meta = entry.meta
    if prefilter.intent_bucket and meta.intent_bucket and meta.intent_bucket != prefilter.intent_bucket:
        return False
    if prefilter.field_types and meta.field_type and meta.field_type not in prefilter.field_types:
        return False
    return meta.scope != "company" or meta.company_slug == prefilter.company_slug


class MemoryCacheStore:
    """Pure-Python parity backend for tests and `--dry-run --once` before migration 004."""

    backend = "memory"
    supports_metadata = True

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _MemoryRow] = {}

    def _find(self, entry_id: str) -> tuple[tuple[str, str], _MemoryRow] | None:
        return next(((key, row) for key, row in self.rows.items() if row.entry.id == entry_id), None)

    def _replace(self, entry_id: str, **changes) -> CacheEntry | None:
        found = self._find(entry_id)
        if found is None:
            return None
        key, row = found
        entry = replace(row.entry, **changes)
        self.rows[key] = _MemoryRow(entry, row.embedding)
        return entry

    async def exact(self, kind, normalized):
        row = self.rows.get((kind, normalized))
        return row.entry if row else None

    async def nearest(self, kind, embedding, threshold, limit=5, *, prefilter=None):
        scored = [(row.entry, cosine(embedding, row.embedding)) for (k, _), row in self.rows.items()
                  if k == kind and row.embedding is not None and passes_prefilter(row.entry, prefilter)]
        scored = [(e, s) for e, s in scored if s >= threshold]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]

    async def upsert(self, kind, question_text, normalized, embedding, answer_text, source, *, meta=None):
        key, now = (kind, normalized), _now()
        current = self.rows.get(key)
        if current is None:
            entry = CacheEntry(id=str(uuid.uuid4()), kind=kind, question_text=question_text,
                               normalized_question=normalized, answer_text=answer_text, source=source,
                               created_at=now, updated_at=now, meta=meta or EntryMeta())
            self.rows[key] = _MemoryRow(entry, embedding)
            return PutResult(entry, "inserted")
        if SOURCE_RANK[source] < SOURCE_RANK[current.entry.source]:
            return PutResult(current.entry, "kept_higher_priority")
        entry = replace(current.entry, question_text=question_text, answer_text=answer_text, source=source,
                        updated_at=now, meta=meta or current.entry.meta, status="active",
                        quarantine_reason=None)
        self.rows[key] = _MemoryRow(entry, embedding if embedding is not None else current.embedding)
        return PutResult(entry, "updated")

    async def record_hit(self, entry_id):
        found = self._find(entry_id)
        if found is not None:
            self._replace(entry_id, hits=found[1].entry.hits + 1, last_hit_at=_now())

    async def get(self, entry_id):
        found = self._find(entry_id)
        return found[1].entry if found else None

    async def set_status(self, entry_id, status, reason=None):
        return self._replace(entry_id, status=status, quarantine_reason=reason if status != "active" else None,
                             updated_at=_now())

    async def bump(self, entry_id, counter):
        if counter not in COUNTERS:
            raise ValueError(f"unknown counter {counter}")
        found = self._find(entry_id)
        if found is None:
            return None
        return self._replace(entry_id, **{counter: getattr(found[1].entry, counter) + 1})

    async def list_entries(self, kind, query, limit, offset, *, status=None):
        needle = normalize_question(query or "")
        rows = [r.entry for r in self.rows.values() if (kind is None or r.entry.kind == kind)
                and (status is None or r.entry.status == status)
                and (not needle or needle in r.entry.normalized_question
                     or needle in normalize_question(r.entry.answer_text))]
        rows.sort(key=lambda e: e.updated_at or _now(), reverse=True)
        return rows[offset:offset + limit], len(rows)

    async def delete(self, entry_id):
        found = self._find(entry_id)
        if found is None:
            return False
        del self.rows[found[0]]
        return True

    async def purge(self, *, status=None, kind=None):
        doomed = [key for key, row in self.rows.items() if (status is None or row.entry.status == status)
                  and (kind is None or row.entry.kind == kind)]
        for key in doomed:
            del self.rows[key]
        return len(doomed)

    async def stats(self):
        return {"total_entries": len(self.rows), "total_hits": sum(r.entry.hits for r in self.rows.values())}

    async def status_counts(self):
        counts = {"active": 0, "quarantined": 0, "expired": 0}
        for row in self.rows.values():
            counts[row.entry.status] = counts.get(row.entry.status, 0) + 1
        return counts


from backend.app.ai_v2.semantic_cache.stores_pg import (  # noqa: E402 - re-export after the memory store
    _ENTRY_COLUMNS,
    NEAREST_SQL,
    UPSERT_SQL,
    PostgresCacheStore,
    _entry,
    vector_literal,
)

__all__ = ["NEAREST_SQL", "UPSERT_SQL", "_ENTRY_COLUMNS", "MemoryCacheStore", "PostgresCacheStore", "_MemoryRow",
           "_entry", "_now", "passes_prefilter", "vector_literal"]
