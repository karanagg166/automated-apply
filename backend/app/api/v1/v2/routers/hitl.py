"""v2 control plane: HITL inbox + Telegram status (Phase 4; same HITLResolutionService as the
Telegram bot) and the dashboard equivalent of Telegram ``/resume <portal>``."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.api.v1.v2.deps import PLATFORM_PATTERN, HITLDep, StoreDep
from backend.app.browser_v2.hitl import Resolution
from backend.app.browser_v2.schemas import (
    HitlPage,
    HitlRead,
    HitlResolutionRead,
    HitlResolveInput,
    HitlStatusName,
    ResumeAuthRead,
    TelegramStatusRead,
)

router = APIRouter()

# --- Phase 4: HITL inbox + Telegram status ---------------------------------------------
RESOLUTION_ERRORS = {"not_found": 404, "already_resolved": 409, "invalid_option": 422, "empty_answer": 422,
                     "answer_too_long": 422, "wrong_kind": 422}


def resolution_read(result: Resolution) -> HitlResolutionRead:
    if not result.ok:
        status = RESOLUTION_ERRORS.get(result.code, 422)
        raise HTTPException(status, result.message)  # invalid_option lists the numbered options
    return HitlResolutionRead.model_validate(result.public())


def hitl_id_or_404(hitl_id: str) -> str:
    from uuid import UUID

    try:
        return str(UUID(hitl_id))
    except ValueError:
        raise HTTPException(404, "HITL request not found") from None


RESOLVE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "HITL request not found"}, 409: {"description": "Already resolved"},
    422: {"description": "Invalid option / empty answer / wrong kind"}}


@router.get("/telegram/status", response_model=TelegramStatusRead)
async def get_telegram_status(store: StoreDep) -> TelegramStatusRead:
    """Bot config + long-polling state persisted by the worker. Never returns the token."""
    from backend.app.telegram_v2.bot import telegram_status

    return TelegramStatusRead.model_validate(await telegram_status(store))


@router.get("/hitl", response_model=HitlPage)
async def list_hitl_requests(
    store: StoreDep,
    status: HitlStatusName | None = "OPEN",
    platform: Annotated[str | None, Query(max_length=40, pattern=PLATFORM_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> HitlPage:
    rows, total = await store.list_hitl(status, platform, limit, offset)
    return HitlPage(items=[HitlRead.model_validate(row.public()) for row in rows], total=total,
                    limit=limit, offset=offset)


@router.post("/hitl/{hitl_id}/resolve", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def resolve_hitl_request(hitl_id: str, data: HitlResolveInput, hitl: HITLDep) -> HitlResolutionRead:
    """Answer & resume: validates options, learns into the semantic cache (cache_answer) and re-enqueues."""
    return resolution_read(await hitl.answer(hitl_id_or_404(hitl_id), data.answer,
                                             cache_answer=data.cache_answer, via="dashboard"))


@router.post("/hitl/{hitl_id}/skip", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def skip_hitl_request(hitl_id: str, hitl: HITLDep) -> HitlResolutionRead:
    return resolution_read(await hitl.skip(hitl_id_or_404(hitl_id), via="dashboard"))


@router.post("/hitl/{hitl_id}/retry", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def retry_hitl_request(hitl_id: str, hitl: HITLDep) -> HitlResolutionRead:
    return resolution_read(await hitl.retry(hitl_id_or_404(hitl_id), via="dashboard"))


@router.post("/portal-rules/{platform}/resume-auth", response_model=ResumeAuthRead,
             responses={404: {"description": "Unknown portal"}})
async def resume_portal_auth(platform: str, hitl: HITLDep) -> ResumeAuthRead:
    """Same as Telegram /resume <portal>: auth_status -> UNKNOWN, open AUTH requests resolved."""
    outcome = await hitl.resume_portal(platform, via="dashboard")
    if not outcome.ok:
        raise HTTPException(404, "Unknown portal")
    return ResumeAuthRead.model_validate(outcome.public())
