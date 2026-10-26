"""Authenticated owner review of browser plans, with no browser commands from clients."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.router import owner_ui
from backend.app.browser.contracts import FillPlan, Review
from backend.app.browser.service import FormService
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/browser", tags=["Browser forms"], route_class=OwnerRoute
)


@router.get("/plans", response_model=list[FillPlan])
async def plans(session: AsyncSession = Depends(get_db_session)):
    rows = (
        await session.scalars(
            select(OwnerPreference)
            .where(OwnerPreference.key.like("fill_plan:%"))
            .order_by(OwnerPreference.created_at.desc())
            .limit(20)
        )
    ).all()
    return [FillPlan.model_validate(r.value) for r in rows]


@router.post("/plans/{plan_id}/review", response_model=FillPlan)
async def review(
    plan_id: UUID,
    data: Review,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    owner_ui(request)
    try:
        return await FormService(session, get_settings()).review(
            plan_id, data.field_ids
        )
    except ValueError:
        raise HTTPException(409, "fill_plan_stale_or_review_rejected") from None


@router.post("/stop")
async def stop(request: Request, session: AsyncSession = Depends(get_db_session)):
    from backend.app.browser.queue import stop_all

    owner_ui(request)
    await stop_all(session)
    return {"status": "cancelled", "submitted": False}


@router.post("/plans/{plan_id}/next")
async def next_step(
    plan_id: UUID, request: Request, session: AsyncSession = Depends(get_db_session)
):
    from datetime import datetime, timezone

    owner_ui(request)
    service = FormService(session, get_settings())
    try:
        _, plan = await service.load(plan_id)
        await service.fresh(plan)
        if (
            plan.mode != "local_automation"
            or plan.state != "finished"
            or not plan.inspection.has_next
        ):
            raise ValueError("invalid_next")
        rows = (
            await session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.like("browser_job:%"))
                .with_for_update()
            )
        ).all()
        job = next((r for r in rows if r.value.get("plan_id") == str(plan_id)), None)
        if (
            not job
            or job.value["state"] != "form_filled"
            or job.value.get("step_count", 1) >= 5
            or datetime.fromisoformat(job.value["expires_at"])
            <= datetime.now(timezone.utc)
        ):
            raise ValueError("invalid_next")
        job.value = {
            **job.value,
            "state": "queued",
            "next_requested": True,
            "step_count": job.value.get("step_count", 1) + 1,
        }
        return {"status": "pending_browser", "submitted": False}
    except ValueError:
        raise HTTPException(409, "next_step_requires_current_completed_form") from None
