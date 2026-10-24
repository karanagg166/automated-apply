"""Existing owner bearer/BFF auth; no policy mutation endpoint for remote clients."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.local_agent.contracts import Actor, Command, PolicyUpdate, Result
from backend.app.local_agent.models import AgentOperation
from backend.app.local_agent.policies import get_policy, update_policy
from backend.app.local_agent.preferences import (
    SearchPreferences,
    get_preferences,
    save_preferences,
)
from backend.app.local_agent.registry import connection_report
from backend.app.local_agent.service import dispatch

router = APIRouter(prefix="/api/v1/local-agent", tags=["Local agent"], route_class=OwnerRoute)


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
    if request.headers.get("X-Agent-Client") or request.headers.get("Origin", "").startswith("chrome-extension:"):
        raise HTTPException(403, "owner_ui_required")
    try:
        return await update_policy(session, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/commands", response_model=Result)
async def owner_command(command: Command, session: AsyncSession = Depends(get_db_session)):
    return await dispatch(session, get_settings(), Actor(channel="owner", identity="primary"), command)


@router.post("/chrome", response_model=Result)
async def chrome_command(command: Command, request: Request, session: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    if (not settings.CHROME_NATIVE_MESSAGING_ENABLED or not settings.CHROME_EXTENSION_ID
            or request.headers.get("X-Agent-Client") != settings.CHROME_EXTENSION_ID):
        raise HTTPException(403, "extension_identity_not_authorized")
    if command.command not in {"health", "connection_status", "get_agent_capabilities", "preview_application_url"}:
        raise HTTPException(403, "extension_capability_denied")
    return await dispatch(session, settings, Actor(channel="chrome", identity=settings.CHROME_EXTENSION_ID), command)


@router.get("/history")
async def history(session: AsyncSession = Depends(get_db_session)):
    rows = (await session.scalars(select(AgentOperation).order_by(AgentOperation.created_at.desc()).limit(50))).all()
    return [{"command": row.command, "actor": row.actor, "created_at": row.created_at,
             "result": row.result} for row in rows]
