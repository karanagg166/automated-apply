"""Owner-protected saved catalog, credit and diagnostics routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session, get_session_factory
from backend.app.schemas.credit import CreditBudgetStatus
from backend.app.schemas.job import JobRead
from backend.app.services.credit_manager import CreditManager
from backend.app.services.saved_data import SavedDataService

router = APIRouter()


@router.get(
    "/api/v1/credits/status",
    response_model=CreditBudgetStatus,
    tags=["Credits"],
    dependencies=[Depends(require_api_token)],
)
async def get_credits_status(
    session: AsyncSession = Depends(get_db_session),
) -> CreditBudgetStatus:
    """Retrieve remaining credits, monthly allocations, and cooldown status across all providers."""
    manager = CreditManager(session)
    return await manager.get_credit_status()


@router.get(
    "/api/v1/jobs",
    response_model=list[JobRead],
    tags=["Jobs"],
    dependencies=[Depends(require_api_token)],
)
async def list_jobs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[JobRead]:
    """List discovered jobs with optional status filter."""
    from backend.app.services.saved_data import SavedDataService

    return await SavedDataService(session).jobs(limit, offset, status)


@router.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_token)])
async def saved_job_detail(
    job_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).job(job_id)


@router.get("/api/v1/jobs/{job_id}/match", dependencies=[Depends(require_api_token)])
async def saved_job_match(
    job_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).match(job_id)


@router.get(
    "/api/v1/companies/{company_id}/details", dependencies=[Depends(require_api_token)]
)
async def saved_company_detail(
    company_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).company(company_id)


@router.get(
    "/api/v1/companies/{company_id}/recommended-contacts",
    dependencies=[Depends(require_api_token)],
)
async def saved_company_contacts(
    company_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    return await SavedDataService(session).contacts(company_id, limit)


@router.get("/api/v1/operations/status", dependencies=[Depends(require_api_token)])
async def operations_status(session: AsyncSession = Depends(get_db_session)):
    from backend.app.operations.diagnostics import operational_status

    return await operational_status(session, get_session_factory(), get_settings())
