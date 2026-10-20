"""Dashboard controls use the same owner authentication and request boundaries."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.resume_sync.review import approve_version, review_changes
from backend.app.resume_sync.schemas import (
    ApproveResume,
    ResumeReviewRead,
    SourceSettings,
    SyncNow,
    SyncResult,
    SyncStatus,
)
from backend.app.resume_sync.service import ResumeSyncService
from backend.app.resume_sync.store import save_source, status

router = APIRouter(prefix="/api/v1/dashboard/resume-sync", tags=["Resume sync"],
                   route_class=OwnerRoute, dependencies=[Depends(require_api_token)])


@router.get("", response_model=SyncStatus)
async def get_status(session: AsyncSession = Depends(get_db_session)):
    return await status(session, get_settings())


@router.put("/source", response_model=SyncStatus)
async def change_source(data: SourceSettings, session: AsyncSession = Depends(get_db_session)):
    return await save_source(session, get_settings(), data)


@router.post("/sync", response_model=SyncResult)
async def sync_now(data: SyncNow, session: AsyncSession = Depends(get_db_session)):
    return await ResumeSyncService(session).sync(data.expected_generation)


@router.get("/versions/{version_id}/review", response_model=ResumeReviewRead)
async def get_changes(version_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await review_changes(session, get_settings(), version_id)


@router.post("/versions/{version_id}/approve", response_model=SyncStatus)
async def approve(version_id: UUID, data: ApproveResume, session: AsyncSession = Depends(get_db_session)):
    return await approve_version(session, get_settings(), version_id, data)
