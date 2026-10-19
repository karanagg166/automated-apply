"""Owner draft review and separately confirmed sends. Approval never sends."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.gmail.schemas import SendRequest
from backend.app.models.outreach import OutreachLog
from backend.app.schemas.outreach import DraftDecision, DraftEdit, DraftInput
from backend.app.services.gmail_sending import GmailSendingService
from backend.app.services.outreach_drafting import (
    DraftConflict,
    OutreachDraftingService,
)

router = APIRouter(
    prefix="/api/v1/outreach",
    tags=["Local outreach drafts"],
    dependencies=[Depends(require_api_token)],
)


def drafting_service(session: AsyncSession = Depends(get_db_session)):
    return OutreachDraftingService(session)


async def execute(awaitable):
    try:
        return await awaitable
    except LookupError:
        raise HTTPException(404, "Draft or contact not found") from None
    except DraftConflict as exc:
        detail = (
            {"code": "send_blocked", "blockers": exc.blockers}
            if hasattr(exc, "blockers")
            else str(exc)
        )
        raise HTTPException(409, detail) from None
    except ValueError:
        raise HTTPException(422, "Invalid draft context or input") from None


@router.post("/drafts/preview")
async def preview(data: DraftInput, service=Depends(drafting_service)):
    return await execute(service.preview(data))


@router.post("/drafts")
async def create(data: DraftInput, service=Depends(drafting_service)):
    return await execute(service.create(data))


@router.get("/drafts")
async def list_drafts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    service=Depends(drafting_service),
):
    ids = (
        await service.session.scalars(
            select(OutreachLog.id)
            .order_by(OutreachLog.created_at.desc(), OutreachLog.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = await service.session.scalar(select(func.count()).select_from(OutreachLog))
    return {
        "drafts": [await service.read(key) for key in ids],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.get("/drafts/{draft_id}")
async def read(draft_id: UUID, service=Depends(drafting_service)):
    return await execute(service.read(draft_id))


@router.patch("/drafts/{draft_id}")
async def edit(draft_id: UUID, data: DraftEdit, service=Depends(drafting_service)):
    return await execute(service.edit(draft_id, data))


@router.post("/drafts/{draft_id}/approve")
async def approve(
    draft_id: UUID, data: DraftDecision, service=Depends(drafting_service)
):
    return await execute(service.decide(draft_id, data.expected_revision, True))


@router.post("/drafts/{draft_id}/reject")
async def reject(
    draft_id: UUID, data: DraftDecision, service=Depends(drafting_service)
):
    return await execute(service.decide(draft_id, data.expected_revision, False))


@router.get("/drafts/{draft_id}/eligibility")
async def eligibility(draft_id: UUID, service=Depends(drafting_service)):
    async def check():
        return await service.eligibility(await service.get(draft_id))

    return await execute(check())


# Only this owner-facing router can initiate Gmail; no MCP registration or worker.


def sending_service(session: AsyncSession = Depends(get_db_session)):
    return GmailSendingService(session)


@router.post("/drafts/{draft_id}/send-preview")
async def send_preview(draft_id: UUID, service=Depends(sending_service)):
    return await execute(service.preview(draft_id, actor="owner"))


@router.post("/drafts/{draft_id}/send")
async def send(draft_id: UUID, data: SendRequest, service=Depends(sending_service)):
    return await execute(service.send(draft_id, data, actor="owner"))


@router.get("/send-attempts/{attempt_id}")
async def send_status(attempt_id: UUID, service=Depends(sending_service)):
    return await execute(service.status(attempt_id))


@router.get("/history")
async def outreach_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    service=Depends(sending_service),
):
    return await execute(service.history(limit, offset))
