"""v2 control plane: AI router status and semantic-cache curation (Phase 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from backend.app.ai_v2.schemas import (
    AIStatusRead,
    SemanticCacheCreate,
    SemanticCacheEntryRead,
    SemanticCachePage,
)
from backend.app.ai_v2.semantic_cache import InvalidCacheEntry
from backend.app.api.v1.v2.deps import AIDep

router = APIRouter()


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
) -> SemanticCachePage:
    entries, total = await ai.cache.store.list_entries(kind, q, limit, offset)
    return SemanticCachePage(items=[SemanticCacheEntryRead(**entry.public()) for entry in entries],
                             total=total, limit=limit, offset=offset)


@router.post("/semantic-cache", response_model=SemanticCacheEntryRead, status_code=201,
             responses={422: {"description": "Invalid question/answer"}})
async def create_semantic_cache_entry(data: SemanticCacheCreate, ai: AIDep) -> SemanticCacheEntryRead:
    """Teach a verified Q&A pair (source='user' outranks profile/LLM answers)."""
    try:
        result = await ai.cache.put(data.kind, data.question_text, data.answer_text, "user")
    except InvalidCacheEntry as exc:
        raise HTTPException(422, str(exc)) from None
    return SemanticCacheEntryRead(**result.entry.public())


@router.delete("/semantic-cache/{entry_id}", status_code=204, response_class=Response,
               responses={404: {"description": "Entry not found"}})
async def delete_semantic_cache_entry(entry_id: str, ai: AIDep) -> Response:
    from uuid import UUID

    try:
        UUID(entry_id)
    except ValueError:
        raise HTTPException(404, "Entry not found") from None
    if not await ai.cache.store.delete(entry_id):
        raise HTTPException(404, "Entry not found")
    return Response(status_code=204)
