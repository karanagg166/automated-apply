"""Owner-authenticated startup boundary; only explicit REST actions execute providers."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session, get_session_factory
from backend.app.services.job_discovery_service import IdempotencyConflict
from backend.app.services.startup_discovery.connectivity import ProviderConnectivity
from backend.app.services.startup_discovery.schemas import (
    ShortlistInput,
    StartupFilters,
    StartupRead,
    StartupRunRequest,
    StartupSearchRead,
)
from backend.app.services.startup_discovery.service import StartupDiscoveryService
from backend.app.services.startup_discovery.source_registry import startup_sources

router = APIRouter(
    prefix="/api/v1/startups",
    tags=["Startup intelligence"],
    dependencies=[Depends(require_api_token)],
)


def service(session):
    return StartupDiscoveryService(session, get_session_factory())


@router.get("/sources")
async def sources():
    return {"sources": startup_sources()}


@router.post("/discovery/preview")
async def preview(
    request: StartupRunRequest, session: AsyncSession = Depends(get_db_session)
):
    return await service(session).preview(request)


@router.post("/discovery/runs")
async def discover(
    request: StartupRunRequest, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await service(session).run(request)
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/discovery/runs/{run_id}")
async def run(run_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await service(session).read_run(run_id)


@router.get("/search", response_model=StartupSearchRead)
async def search(
    filters: Annotated[StartupFilters, Query()],
    session: AsyncSession = Depends(get_db_session),
):
    return await service(session).search(filters)


# Lists use a typed JSON search as well; GET scalar parameters remain convenient.
@router.post("/search", response_model=StartupSearchRead)
async def filtered_search(
    filters: StartupFilters, session: AsyncSession = Depends(get_db_session)
):
    return await service(session).search(filters)


@router.get("/shortlist", response_model=StartupSearchRead)
async def shortlist(
    filters: Annotated[StartupFilters, Query()],
    session: AsyncSession = Depends(get_db_session),
):
    return await service(session).search(filters, shortlisted=True)


@router.get("/integrations/status")
async def integrations(session: AsyncSession = Depends(get_db_session)):
    return await ProviderConnectivity(session, get_session_factory()).status()


@router.post("/integrations/{provider}/check")
async def check(provider: str, session: AsyncSession = Depends(get_db_session)):
    return await ProviderConnectivity(session, get_session_factory()).check(provider)


@router.get("/{company_id}", response_model=StartupRead)
async def detail(company_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await service(session).detail(company_id)


@router.get("/{company_id}/jobs")
async def jobs(company_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await service(session).jobs(company_id)


@router.get("/{company_id}/evidence")
async def evidence(company_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await service(session).evidence(company_id)


@router.post("/{company_id}/shortlist")
async def save_shortlist(
    company_id: UUID,
    request: ShortlistInput,
    session: AsyncSession = Depends(get_db_session),
):
    return await service(session).shortlist(company_id, request)
