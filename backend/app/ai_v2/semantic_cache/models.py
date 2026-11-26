"""Semantic-cache domain types: limits, normalization, entry/hit DTOs and the store Protocol.

Imports nothing from the stores, the facade or the embeddings backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

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
