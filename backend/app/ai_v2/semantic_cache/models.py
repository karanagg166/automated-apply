"""Semantic-cache domain types: limits, normalization, entry/hit DTOs and the store Protocol.

Imports nothing from the stores, the facade or the embeddings backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

DEFAULT_THRESHOLD = 0.88
SOURCES = ("user", "profile", "llm")
COUNTERS = ("human_override_count", "form_validation_error_count")
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


# --- storage ----------------------------------------------------------------------------
@dataclass(frozen=True)
class EntryMeta:
    """Phase 4 metadata written with an entry (columns added by followup 006). Every field is
    optional so pre-006 rows (all None) keep working; the guards re-derive what is missing."""

    field_type: str | None = None
    intent_bucket: str | None = None
    entities: dict[str, Any] = field(default_factory=dict)
    scope: str = "global"  # global | company
    company_slug: str | None = None
    profile_version_hash: str | None = None
    invalidation_scope: str | None = None  # factual_profile | behavioral_stable | company_scoped
    expires_at: datetime | None = None
    verified_by: str | None = None  # human | judge:<provider>:<score> | profile | None (legacy)
    cache_key: str | None = None
    options_hash: str | None = None


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
    meta: EntryMeta = field(default_factory=EntryMeta)
    status: str = "active"  # active | quarantined | expired
    human_override_count: int = 0
    form_validation_error_count: int = 0
    last_hit_at: datetime | None = None
    quarantine_reason: str | None = None

    @property
    def trust(self) -> str:
        """human_verified (owner answer) > llm_verified (judge-approved) > profile > unverified llm."""
        if self.source == "user":
            return "human_verified"
        if self.source == "llm":
            return "llm_verified" if (self.meta.verified_by or "").startswith("judge:") else "llm_unverified"
        return self.source

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "question_text": self.question_text,
                "answer_text": self.answer_text, "source": self.source, "hits": self.hits,
                "created_at": self.created_at, "updated_at": self.updated_at}

    def detail(self) -> dict[str, Any]:
        meta = self.meta
        return self.public() | {
            "normalized_question": self.normalized_question, "status": self.status, "trust": self.trust,
            "quarantine_reason": self.quarantine_reason, "human_override_count": self.human_override_count,
            "form_validation_error_count": self.form_validation_error_count, "last_hit_at": self.last_hit_at,
            "field_type": meta.field_type, "intent_bucket": meta.intent_bucket, "entities": meta.entities,
            "scope": meta.scope, "company_slug": meta.company_slug,
            "profile_version_hash": meta.profile_version_hash, "invalidation_scope": meta.invalidation_scope,
            "expires_at": meta.expires_at, "verified_by": meta.verified_by, "cache_key": meta.cache_key}


@dataclass(frozen=True)
class QuestionContext:
    """What the caller knows about the live form field. Everything is optional; with no context the
    cache behaves like the pre-Phase-4 cache (constructor threshold, qualifier + polarity guards)."""

    field_kind: str | None = None  # DOM/HITL kind: radio, select, combobox, checkbox, textarea, text, ...
    options: tuple[str, ...] = ()
    company: str | None = None
    role_country: str | None = None
    profile_hash: str | None = None
    platform: str | None = None


@dataclass(frozen=True)
class Prefilter:
    """Hard SQL prefilters applied before the vector ranking (NULL columns = legacy rows, which the
    Python guards re-check)."""

    intent_bucket: str | None = None
    field_types: tuple[str, ...] = ()
    company_slug: str | None = None


@dataclass(frozen=True)
class PutResult:
    entry: CacheEntry
    outcome: str  # inserted | updated | kept_higher_priority


class CacheStore(Protocol):
    backend: str

    async def exact(self, kind: str, normalized: str) -> CacheEntry | None: ...

    async def nearest(self, kind: str, embedding: list[float], threshold: float, limit: int = 5, *,
                      prefilter: Prefilter | None = None) -> list[tuple[CacheEntry, float]]: ...

    async def upsert(self, kind: str, question_text: str, normalized: str, embedding: list[float] | None,
                     answer_text: str, source: str, *, meta: EntryMeta | None = None) -> PutResult: ...

    async def record_hit(self, entry_id: str) -> None: ...

    async def get(self, entry_id: str) -> CacheEntry | None: ...

    async def set_status(self, entry_id: str, status: str, reason: str | None = None) -> CacheEntry | None: ...

    async def bump(self, entry_id: str, counter: str) -> CacheEntry | None: ...

    async def list_entries(self, kind: str | None, query: str | None, limit: int, offset: int, *,
                           status: str | None = None) -> tuple[list[CacheEntry], int]: ...

    async def delete(self, entry_id: str) -> bool: ...

    async def purge(self, *, status: str | None = None, kind: str | None = None) -> int: ...

    async def stats(self) -> dict[str, int]: ...

    async def status_counts(self) -> dict[str, int]: ...
