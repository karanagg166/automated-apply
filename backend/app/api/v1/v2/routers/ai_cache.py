"""v2 control plane: AI router status and semantic-cache curation (Phase 3 + Phase 4 admin).

Phase 4 adds: status filter on the list, decision/status stats, per-entry inspect, quarantine /
unquarantine, purge of quarantined/expired rows and a dry-run `explain` lookup (no hit counted).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.ai_v2.schemas import (
    AIStatusRead,
    SemanticCacheCreate,
    SemanticCacheEntryRead,
    SemanticCachePage,
)
from backend.app.ai_v2.semantic_cache import InvalidCacheEntry, QuestionContext
from backend.app.api.v1.v2.deps import AIDep

router = APIRouter()
CacheStatus = Literal["active", "quarantined", "expired"]


class SemanticCacheEntryDetail(SemanticCacheEntryRead):
    normalized_question: str
    status: str
    trust: str
    quarantine_reason: str | None = None
    human_override_count: int = 0
    form_validation_error_count: int = 0
    last_hit_at: Any = None
    field_type: str | None = None
    intent_bucket: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    scope: str = "global"
    company_slug: str | None = None
    profile_version_hash: str | None = None
    invalidation_scope: str | None = None
    expires_at: Any = None
    verified_by: str | None = None
    cache_key: str | None = None


class QuarantineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="owner_quarantine", min_length=1, max_length=200)


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["quarantined", "expired"]
    kind: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=400)
    company: str | None = Field(default=None, max_length=200)
    field_kind: str | None = Field(default=None, max_length=40)
    kind: str = Field(default="screening_qa", pattern=r"^[a-z][a-z0-9_]{1,39}$")


def _entry_id(entry_id: str) -> str:
    try:
        UUID(entry_id)
    except ValueError:
        raise HTTPException(404, "Entry not found") from None
    return entry_id


# --- AI router + semantic cache (Phase 3) ---------------------------------------------
@router.get("/ai/status", response_model=AIStatusRead)
async def ai_status(ai: AIDep) -> AIStatusRead:
    return AIStatusRead.model_validate(await ai.status())


@router.get("/semantic-cache", response_model=SemanticCachePage)
async def list_semantic_cache(
    ai: AIDep,
    kind: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,39}$")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    status: CacheStatus | None = None,
) -> SemanticCachePage:
    entries, total = await ai.cache.store.list_entries(kind, q, limit, offset, status=status)
    return SemanticCachePage(items=[SemanticCacheEntryRead(**entry.public()) for entry in entries],
                             total=total, limit=limit, offset=offset)


@router.post("/semantic-cache", response_model=SemanticCacheEntryRead, status_code=201,
             responses={422: {"description": "Invalid or non-cacheable question/answer"}})
async def create_semantic_cache_entry(data: SemanticCacheCreate, ai: AIDep) -> SemanticCacheEntryRead:
    """Teach a verified Q&A pair (source='user' outranks profile/LLM answers)."""
    try:
        result = await ai.cache.put(data.kind, data.question_text, data.answer_text, "user")
    except InvalidCacheEntry as exc:
        raise HTTPException(422, str(exc)) from None
    return SemanticCacheEntryRead(**result.entry.public())


# --- Phase 4 admin (declared before /{entry_id} so the literal paths win) --------------------
@router.get("/semantic-cache/stats")
async def semantic_cache_stats(ai: AIDep) -> dict[str, Any]:
    """Entry/hit totals, status counts (active/quarantined/expired), thresholds and decision counters."""
    return await ai.cache.stats()


@router.post("/semantic-cache/purge")
async def purge_semantic_cache(data: PurgeRequest, ai: AIDep) -> dict[str, int]:
    """Delete every quarantined (or expired) entry, optionally of one kind. Active rows are never purged."""
    return {"deleted": await ai.cache.purge(status=data.status, kind=data.kind)}


@router.post("/semantic-cache/explain")
async def explain_semantic_cache(data: ExplainRequest, ai: AIDep) -> dict[str, Any]:
    """Dry-run lookup: what the cache WOULD answer for this field (no hit is counted)."""
    context = QuestionContext(field_kind=data.field_kind, options=tuple(data.options), company=data.company)
    query, hit = await ai.cache.explain(data.kind, data.question, context)
    return {"intent_bucket": query.intent, "field_type": query.field_type, "cache_policy": query.policy,
            "invalidation_scope": query.invalidation, "entities": query.qualifiers.entities(),
            "hit": None if hit is None else {"id": hit.entry.id, "match": hit.match,
                                             "similarity": round(hit.similarity, 4),
                                             "answer": hit.answer or hit.entry.answer_text}}


@router.get("/semantic-cache/{entry_id}", response_model=SemanticCacheEntryDetail,
            responses={404: {"description": "Entry not found"}})
async def inspect_semantic_cache_entry(entry_id: str, ai: AIDep) -> SemanticCacheEntryDetail:
    entry = await ai.cache.store.get(_entry_id(entry_id))
    if entry is None:
        raise HTTPException(404, "Entry not found")
    return SemanticCacheEntryDetail(**entry.detail())


@router.post("/semantic-cache/{entry_id}/quarantine", response_model=SemanticCacheEntryDetail,
             responses={404: {"description": "Entry not found"}})
async def quarantine_semantic_cache_entry(entry_id: str, data: QuarantineRequest,
                                          ai: AIDep) -> SemanticCacheEntryDetail:
    entry = await ai.cache.quarantine(_entry_id(entry_id), data.reason)
    if entry is None:
        raise HTTPException(404, "Entry not found")
    return SemanticCacheEntryDetail(**entry.detail())


@router.post("/semantic-cache/{entry_id}/unquarantine", response_model=SemanticCacheEntryDetail,
             responses={404: {"description": "Entry not found"}})
async def unquarantine_semantic_cache_entry(entry_id: str, ai: AIDep) -> SemanticCacheEntryDetail:
    entry = await ai.cache.unquarantine(_entry_id(entry_id))
    if entry is None:
        raise HTTPException(404, "Entry not found")
    return SemanticCacheEntryDetail(**entry.detail())


@router.delete("/semantic-cache/{entry_id}", status_code=204, response_class=Response,
               responses={404: {"description": "Entry not found"}})
async def delete_semantic_cache_entry(entry_id: str, ai: AIDep) -> Response:
    if not await ai.cache.store.delete(_entry_id(entry_id)):
        raise HTTPException(404, "Entry not found")
    return Response(status_code=204)
