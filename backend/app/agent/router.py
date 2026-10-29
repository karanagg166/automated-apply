"""Authenticated dashboard boundary for the shared command queue."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent import store
from backend.app.agent.contracts import Approval, Campaign, Message
from backend.app.agent.tools import ToolDenied
from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session
from backend.app.local_agent.contracts import Actor
from backend.app.models.application_answer import LLMMonthlyUsage

router = APIRouter(prefix="/api/v1/agent", tags=["Command agent"], route_class=OwnerRoute)
OWNER = Actor(channel="owner", identity="primary")


def owner_ui(request):
    if request.headers.get("X-Agent-Client") or request.headers.get("Origin", "").startswith("chrome-extension:"):
        raise HTTPException(403, "owner_ui_required")


@router.post("/commands", response_model=Campaign)
async def command(data: Message, request: Request, session: AsyncSession = Depends(get_db_session)):
    owner_ui(request)
    try:
        return await store.intake(session, get_settings(), OWNER, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/campaigns", response_model=list[Campaign])
async def history(session: AsyncSession = Depends(get_db_session)):
    return [Campaign.model_validate(r.value) for r in await store.campaigns(session)]


@router.get("/campaigns/{campaign_id}", response_model=Campaign)
async def status(campaign_id: UUID, session: AsyncSession = Depends(get_db_session)):
    try:
        return (await store.load(session, campaign_id))[1]
    except ToolDenied:
        raise HTTPException(404, "campaign_not_found") from None


@router.post("/campaigns/{campaign_id}/approve", response_model=Campaign)
async def approve(campaign_id: UUID, data: Approval, request: Request, session: AsyncSession = Depends(get_db_session)):
    owner_ui(request)
    try:
        return await store.approve(session, get_settings(), OWNER, campaign_id, data)
    except ToolDenied as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/campaigns/{campaign_id}/cancel", response_model=Campaign)
async def cancel(campaign_id: UUID, request: Request, session: AsyncSession = Depends(get_db_session)):
    owner_ui(request)
    try:
        return await store.cancel(session, get_settings(), OWNER, campaign_id)
    except ToolDenied:
        raise HTTPException(404, "campaign_not_found") from None


@router.get("/status")
async def provider_status(session: AsyncSession = Depends(get_db_session)):
    from datetime import datetime, timezone
    settings = get_settings()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = await session.scalar(select(LLMMonthlyUsage).where(
        LLMMonthlyUsage.provider == "cohere", LLMMonthlyUsage.month == month))
    cap = min(settings.LLM_MONTHLY_MAX_REQUESTS, settings.COHERE_MONTHLY_MAX_REQUESTS,
              settings.COHERE_MONTHLY_MAX_TOKENS // (settings.LLM_MAX_INPUT_CHARS + settings.LLM_MAX_OUTPUT_TOKENS))
    configured = bool(settings.COHERE_API_KEY)
    enabled = configured and settings.COHERE_ENABLED and settings.COHERE_EVALUATION_KEY_CONFIRMED
    worker = await session.get(OwnerPreference, "agent_worker:primary")
    last = worker.value.get("heartbeat_at") if worker else None
    ready = bool(last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 150)
    from backend.app.browser.chrome_profiles import listing
    chrome = await listing(session, settings)
    selected = next((profile for profile in chrome["profiles"] if profile["selected"]), None)
    browser_last = selected["last_heartbeat"] if selected else None
    browser_ready = bool(selected and selected["status"] == "CONNECTED" and selected["commands_enabled"] and settings.CHROME_PROFILE_COMMANDS_ENABLED)
    return {"browser_worker_ready": browser_ready, "browser_last_heartbeat": browser_last,
            "browser_fill_enabled": settings.BROWSER_FILL_ENABLED, "browser_availability": "available" if browser_ready else "PROFILE_COMMANDS_DISABLED" if selected and selected["status"] == "CONNECTED" else "PROFILE_OFFLINE",
            "worker_ready": ready, "worker_last_heartbeat": last,
            "execution": "available" if ready else "pending_worker_unavailable",
            "provider": "cohere", "model": settings.COHERE_MODEL,
            "state": "configured_not_live_verified" if enabled else "not_configured" if not configured else "authorization_required",
            "owner_text_authorized": settings.COHERE_OWNER_TEXT_AUTHORIZED,
            "candidate_data_authorized": settings.COHERE_CANDIDATE_DATA_AUTHORIZED,
            "local_request_cap": cap, "local_requests_remaining": max(0, cap - (usage.requests if usage else 0)),
            "provider_quota_remaining": None, "quota_scope": "local_installation_only",
            "input_tokens": usage.input_tokens if usage else 0, "output_tokens": usage.output_tokens if usage else 0,
            "submissions_enabled": settings.BROWSER_SUBMIT_ENABLED and settings.ENVIRONMENT == "testing" and bool(settings.BROWSER_FIXTURE_ORIGIN), "submission_scope": "localhost_fixtures_only", "email_sending_enabled": False}
