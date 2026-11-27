"""PostgresCacheStore: public.semantic_cache over the shared asyncpg connection.

Two modes, detected once per store:
  v2      followup 006 applied: metadata columns, SQL prefilters, status / counters persisted.
  legacy  only the 004 table exists (code deployed before the migration): the original SQL runs
          unchanged, metadata is derived in Python by the guards, and a quarantine deletes the row
          (the only way to stop serving it without a status column).
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from backend.app.ai_v2.semantic_cache.models import (
    COUNTERS,
    CacheEntry,
    EntryMeta,
    PutResult,
    normalize_question,
)

logger = logging.getLogger("backend.app.ai_v2.semantic_cache")


def vector_literal(embedding: list[float]) -> str:
    """pgvector text input format: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.7g}" for x in embedding) + "]"


_ENTRY_COLUMNS = ("id::text AS id, kind, question_text, normalized_question, answer_text, source, hits, "
                  "created_at, updated_at")
_V2_COLUMNS = (_ENTRY_COLUMNS + ", field_type, intent_bucket, entities::text AS entities, scope, company_slug, "
               "profile_version_hash, invalidation_scope, expires_at, verified_by, cache_key, options_hash, "
               "status, human_override_count, form_validation_error_count, last_hit_at, quarantine_reason")
_DISTANCE = "embedding OPERATOR(extensions.<=>) $2::text::extensions.vector"
_RANK = "(CASE {0}.source WHEN 'user' THEN 3 WHEN 'profile' THEN 2 ELSE 1 END)"
# OPERATOR(extensions.<=>) resolves pgvector's cosine-distance operator without relying on
# search_path (the extension lives in schema `extensions` on Supabase).
NEAREST_SQL = (
    f"SELECT {_ENTRY_COLUMNS}, 1 - ({_DISTANCE}) AS similarity "
    "FROM public.semantic_cache WHERE kind = $1 AND embedding IS NOT NULL "
    f"AND 1 - ({_DISTANCE}) >= $3 "
    f"ORDER BY {_DISTANCE} LIMIT $4")
UPSERT_SQL = (
    "INSERT INTO public.semantic_cache (kind, question_text, normalized_question, embedding, answer_text, source) "
    "VALUES ($1, $2, $3, $4::text::extensions.vector, $5, $6) "
    "ON CONFLICT (kind, normalized_question) DO UPDATE SET "
    "question_text = EXCLUDED.question_text, answer_text = EXCLUDED.answer_text, source = EXCLUDED.source, "
    "embedding = COALESCE(EXCLUDED.embedding, public.semantic_cache.embedding), updated_at = now() "
    "WHERE (CASE EXCLUDED.source WHEN 'user' THEN 3 WHEN 'profile' THEN 2 ELSE 1 END) >= "
    "(CASE public.semantic_cache.source WHEN 'user' THEN 3 WHEN 'profile' THEN 2 ELSE 1 END) "
    f"RETURNING {_ENTRY_COLUMNS}, (xmax = 0) AS inserted")
# Hard prefilters run inside the index scan: status/expiry, intent, field type and company scope
# (NULL metadata = pre-006 row; the Python guards classify those).
NEAREST_V2_SQL = (
    f"SELECT {_V2_COLUMNS}, 1 - ({_DISTANCE}) AS similarity "
    "FROM public.semantic_cache WHERE kind = $1 AND embedding IS NOT NULL AND status = 'active' "
    "AND (expires_at IS NULL OR expires_at > now()) "
    "AND ($5::text IS NULL OR intent_bucket IS NULL OR intent_bucket = $5) "
    "AND ($6::text[] IS NULL OR field_type IS NULL OR field_type = ANY($6::text[])) "
    "AND (scope <> 'company' OR company_slug IS NOT DISTINCT FROM $7) "
    f"AND 1 - ({_DISTANCE}) >= $3 "
    f"ORDER BY {_DISTANCE} LIMIT $4")
_META_COLUMNS = ("field_type", "intent_bucket", "entities", "scope", "company_slug", "profile_version_hash",
                 "invalidation_scope", "expires_at", "verified_by", "cache_key", "options_hash")
UPSERT_V2_SQL = (
    "INSERT INTO public.semantic_cache (kind, question_text, normalized_question, embedding, answer_text, source, "
    + ", ".join(_META_COLUMNS) + ") VALUES ($1, $2, $3, $4::text::extensions.vector, $5, $6, $7, $8, $9::jsonb, "
    "$10, $11, $12, $13, $14, $15, $16, $17) "
    "ON CONFLICT (kind, normalized_question) DO UPDATE SET "
    "question_text = EXCLUDED.question_text, answer_text = EXCLUDED.answer_text, source = EXCLUDED.source, "
    "embedding = COALESCE(EXCLUDED.embedding, public.semantic_cache.embedding), "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _META_COLUMNS)
    + ", status = 'active', quarantine_reason = NULL, updated_at = now() "
    f"WHERE {_RANK.format('EXCLUDED')} >= {_RANK.format('public.semantic_cache')} "
    f"RETURNING {_V2_COLUMNS}, (xmax = 0) AS inserted")


def _get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _entry(row: Any) -> CacheEntry:
    entities = _get(row, "entities")
    meta = EntryMeta(
        field_type=_get(row, "field_type"), intent_bucket=_get(row, "intent_bucket"),
        entities=json.loads(entities) if isinstance(entities, str) and entities else {},
        scope=_get(row, "scope") or "global", company_slug=_get(row, "company_slug"),
        profile_version_hash=_get(row, "profile_version_hash"), invalidation_scope=_get(row, "invalidation_scope"),
        expires_at=_get(row, "expires_at"), verified_by=_get(row, "verified_by"), cache_key=_get(row, "cache_key"),
        options_hash=_get(row, "options_hash"))
    return CacheEntry(id=row["id"], kind=row["kind"], question_text=row["question_text"],
                      normalized_question=row["normalized_question"], answer_text=row["answer_text"],
                      source=row["source"], hits=row["hits"], created_at=row["created_at"],
                      updated_at=row["updated_at"], meta=meta, status=_get(row, "status") or "active",
                      human_override_count=_get(row, "human_override_count") or 0,
                      form_validation_error_count=_get(row, "form_validation_error_count") or 0,
                      last_hit_at=_get(row, "last_hit_at"), quarantine_reason=_get(row, "quarantine_reason"))


class PostgresCacheStore:
    """public.semantic_cache over one asyncpg connection (shared with the v2 store)."""

    backend = "postgres"

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self._v2: bool | None = None

    @staticmethod
    async def ready(connection: Any) -> bool:
        return bool(await connection.fetchval("SELECT to_regclass('public.semantic_cache') IS NOT NULL"))

    async def metadata_ready(self) -> bool:
        """True once followup 006 added the Phase 4 columns (checked once per store)."""
        if self._v2 is None:
            self._v2 = bool(await self.connection.fetchval(
                "SELECT count(*) = 3 FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'semantic_cache' AND column_name IN ('status', 'intent_bucket', 'cache_key')"))
        return self._v2

    @property
    def supports_metadata(self) -> bool:
        return bool(self._v2)

    async def _cols(self) -> str:
        return _V2_COLUMNS if await self.metadata_ready() else _ENTRY_COLUMNS

    async def exact(self, kind, normalized):
        row = await self.connection.fetchrow(
            f"SELECT {await self._cols()} FROM public.semantic_cache WHERE kind=$1 AND normalized_question=$2",
            kind, normalized)
        return _entry(row) if row else None

    async def nearest(self, kind, embedding, threshold, limit=5, *, prefilter=None):
        vector = vector_literal(embedding)
        if not await self.metadata_ready():
            rows = await self.connection.fetch(NEAREST_SQL, kind, vector, threshold, limit)
        else:
            rows = await self.connection.fetch(
                NEAREST_V2_SQL, kind, vector, threshold, limit,
                prefilter.intent_bucket if prefilter else None,
                list(prefilter.field_types) if prefilter and prefilter.field_types else None,
                prefilter.company_slug if prefilter else None)
        return [(_entry(row), float(row["similarity"])) for row in rows]

    async def upsert(self, kind, question_text, normalized, embedding, answer_text, source, *, meta=None):
        vector = vector_literal(embedding) if embedding is not None else None
        if not await self.metadata_ready():
            row = await self.connection.fetchrow(UPSERT_SQL, kind, question_text, normalized, vector, answer_text,
                                                 source)
        else:
            m = meta or EntryMeta()
            row = await self.connection.fetchrow(
                UPSERT_V2_SQL, kind, question_text, normalized, vector, answer_text, source, m.field_type,
                m.intent_bucket, json.dumps(m.entities or {}), m.scope, m.company_slug, m.profile_version_hash,
                m.invalidation_scope, m.expires_at, m.verified_by, m.cache_key, m.options_hash)
        if row is None:
            existing = await self.exact(kind, normalized)
            assert existing is not None
            return PutResult(existing, "kept_higher_priority")
        return PutResult(_entry(row), "inserted" if row["inserted"] else "updated")

    async def record_hit(self, entry_id):
        extra = ", last_hit_at = now()" if await self.metadata_ready() else ""
        await self.connection.execute(
            f"UPDATE public.semantic_cache SET hits = hits + 1{extra} WHERE id = $1::uuid", entry_id)

    async def get(self, entry_id):
        row = await self.connection.fetchrow(
            f"SELECT {await self._cols()} FROM public.semantic_cache WHERE id = $1::uuid", entry_id)
        return _entry(row) if row else None

    async def set_status(self, entry_id, status, reason=None):
        if not await self.metadata_ready():
            entry = await self.get(entry_id)
            if entry is not None and status != "active":
                logger.warning("semantic_cache legacy_schema quarantine=delete id=%s reason=%s", entry_id, reason)
                await self.delete(entry_id)
                return replace(entry, status=status, quarantine_reason=reason)
            return entry
        row = await self.connection.fetchrow(
            f"UPDATE public.semantic_cache SET status = $2, quarantine_reason = $3, updated_at = now() "
            f"WHERE id = $1::uuid RETURNING {_V2_COLUMNS}",
            entry_id, status, (reason or "")[:300] if status != "active" else None)
        return _entry(row) if row else None

    async def bump(self, entry_id, counter):
        if counter not in COUNTERS:
            raise ValueError(f"unknown counter {counter}")
        if not await self.metadata_ready():
            return await self.get(entry_id)
        row = await self.connection.fetchrow(
            f"UPDATE public.semantic_cache SET {counter} = {counter} + 1 WHERE id = $1::uuid "
            f"RETURNING {_V2_COLUMNS}", entry_id)
        return _entry(row) if row else None

    async def list_entries(self, kind, query, limit, offset, *, status=None):
        needle = normalize_question(query or "")
        where, args = ["($1::text IS NULL OR kind = $1)"], [kind]
        if needle:
            args.append(f"%{needle}%")
            where.append(f"(normalized_question LIKE ${len(args)} OR lower(answer_text) LIKE ${len(args)})")
        if status is not None and await self.metadata_ready():
            args.append(status)
            where.append(f"status = ${len(args)}")
        clause = " AND ".join(where)
        total = await self.connection.fetchval(f"SELECT count(*) FROM public.semantic_cache WHERE {clause}", *args)
        rows = await self.connection.fetch(
            f"SELECT {await self._cols()} FROM public.semantic_cache WHERE {clause} "
            f"ORDER BY updated_at DESC, id LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}", *args, limit, offset)
        return [_entry(row) for row in rows], int(total or 0)

    async def delete(self, entry_id):
        result = await self.connection.execute("DELETE FROM public.semantic_cache WHERE id = $1::uuid", entry_id)
        return str(result).endswith(" 1")

    async def purge(self, *, status=None, kind=None):
        if status is not None and not await self.metadata_ready():
            return 0 if status != "active" else await self.purge(kind=kind)
        where, args = ["($1::text IS NULL OR kind = $1)"], [kind]
        if status is not None:
            args.append(status)
            where.append("status = $2")
        result = await self.connection.execute(
            f"DELETE FROM public.semantic_cache WHERE {' AND '.join(where)}", *args)
        return int(str(result).split()[-1] or 0)

    async def stats(self):
        row = await self.connection.fetchrow(
            "SELECT count(*) AS total_entries, COALESCE(sum(hits), 0) AS total_hits FROM public.semantic_cache")
        return {"total_entries": int(row["total_entries"]), "total_hits": int(row["total_hits"])}

    async def status_counts(self):
        if not await self.metadata_ready():
            return {"active": (await self.stats())["total_entries"], "quarantined": 0, "expired": 0}
        rows = await self.connection.fetch("SELECT status, count(*) AS n FROM public.semantic_cache GROUP BY status")
        counts = {"active": 0, "quarantined": 0, "expired": 0}
        counts.update({row["status"]: int(row["n"]) for row in rows})
        return counts
