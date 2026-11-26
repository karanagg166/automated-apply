"""Semantic-cache backends: MemoryCacheStore and PostgresCacheStore (pgvector)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from backend.app.ai_v2.embeddings import cosine
from backend.app.ai_v2.semantic_cache.models import (
    SOURCE_RANK,
    CacheEntry,
    PutResult,
    normalize_question,
)


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
