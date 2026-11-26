"""Existing owner bearer/BFF auth; no policy mutation endpoint for remote clients."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import owner_ui
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.local_agent.contracts import PolicyUpdate
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import get_policy, update_policy
from backend.app.local_agent.preferences import (
    SearchPreferences,
    get_preferences,
    save_preferences,
)
from backend.app.local_agent.profile_confirmation import (
    ProfileConfirmation,
    confirm_profile,
)
from backend.app.local_agent.registry import connection_report

router = APIRouter(prefix="/api/v1/local-agent", tags=["Local agent"], route_class=OwnerRoute)


@router.post("/profile-confirmation")
async def profile_confirmation(data: ProfileConfirmation, request: Request,
                               session: AsyncSession = Depends(get_db_session)):
    from backend.app.models.candidate_profile import CandidateProfile
    owner_ui(request)
    profile = await session.scalar(select(CandidateProfile).where(
        CandidateProfile.singleton_key == "primary").with_for_update())
    try:
        return await confirm_profile(session, profile, data.expected_version)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/platforms")
async def platforms(session: AsyncSession = Depends(get_db_session)):
    from backend.app.local_agent.platforms import platform_connections
    return await platform_connections(session)


@router.post("/platforms/{platform}/accept-manual")
async def accept_platform_manual(platform: str, request: Request,
                                 session: AsyncSession = Depends(get_db_session)):
    from backend.app.local_agent.platforms import accept_manual_capability
    owner_ui(request)
    try:
        return await accept_manual_capability(session, platform)
    except ValueError:
        raise HTTPException(404, "unsupported_platform") from None


@router.delete("/platforms/{platform}")
async def forget_platform(platform: str, session: AsyncSession = Depends(get_db_session)):
    from backend.app.local_agent.platforms import save_observation
    try:
        return await save_observation(session, platform, "forgotten")
    except ValueError:
        raise HTTPException(404, "unsupported_platform") from None


@router.get("/search-preferences", response_model=SearchPreferences)
async def search_preferences(session: AsyncSession = Depends(get_db_session)):
    return await get_preferences(session)


@router.put("/search-preferences", response_model=SearchPreferences)
async def update_search_preferences(data: SearchPreferences, session: AsyncSession = Depends(get_db_session)):
    return await save_preferences(session, data)


@router.get("/connections")
async def connections(session: AsyncSession = Depends(get_db_session)):
    return await connection_report(session, get_settings(), api_request=True)


@router.get("/policy")
async def policy(session: AsyncSession = Depends(get_db_session)):
    return await get_policy(session)


@router.put("/policy")
async def save_policy(data: PolicyUpdate, request: Request, session: AsyncSession = Depends(get_db_session)):
    # Only the existing authenticated BFF exposes this route to its CSRF-protected owner UI.
    # Native and Telegram never proxy arbitrary endpoints.
    owner_ui(request)
    try:
        return await update_policy(session, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/history")
async def history(session: AsyncSession = Depends(get_db_session)):
    rows = (await session.scalars(select(AgentOperation).order_by(AgentOperation.created_at.desc()).limit(50))).all()
    return [{"command": row.command, "actor": row.actor, "created_at": row.created_at,
             "result": row.result} for row in rows]
