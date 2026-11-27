"""Private automation controls, protected by the existing owner boundary."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.automation.models import AutomationExecution
from backend.app.automation.schemas import ScheduleUpdate
from backend.app.automation.store import (
    configuration,
    current_matches,
    execution_output,
    preview,
    schedule,
    status,
    update_schedule,
)
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/dashboard/automation",
    tags=["Automation"],
    route_class=OwnerRoute,
    dependencies=[Depends(require_api_token)],
)


@router.get("")
async def get_status(session: AsyncSession = Depends(get_db_session)):
    return await status(session, get_settings())


@router.put("")
async def configure(
    data: ScheduleUpdate, session: AsyncSession = Depends(get_db_session)
):
    await update_schedule(session, data, get_settings())
    return await status(session, get_settings())


@router.post("/preview")
async def plan(session: AsyncSession = Depends(get_db_session)):
    return await preview(session, get_settings())


@router.get("/history")
async def history(
    state: Literal[
        "pending", "claimed", "running", "completed", "partial", "failed", "blocked"
    ]
    | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    session: AsyncSession = Depends(get_db_session),
):
    query = (
        select(AutomationExecution)
        .order_by(AutomationExecution.created_at.desc(), AutomationExecution.id)
        .offset(offset)
        .limit(limit)
    )
    if state:
        query = query.where(AutomationExecution.state == state)
    return {
        "executions": [
            execution_output(t) for t in (await session.scalars(query)).all()
        ]
    }


@router.get("/matches")
async def matches(session: AsyncSession = Depends(get_db_session)):
    row = await schedule(session)
    return {
        "matches": [
            {
                "job_id": str(m.job_id),
                "profile_version": m.profile_version,
                "scored_at": m.scored_at,
                **m.result,
            }
            for m in await current_matches(session, configuration(row))
        ]
    }
