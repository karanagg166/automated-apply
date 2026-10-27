"""Owner-only, bounded provider metadata checks. No Actor dispatch endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.schemas import Contract
from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.session import get_db_session, get_session_factory
from backend.app.schemas.discovery import DiscoveryError
from backend.app.services.providers.apify import INVESTIGATED_ACTORS, OfficialApifyAPI
from backend.app.services.startup_discovery.connectivity import claim_access

router = APIRouter(
    prefix="/api/v1/integrations/providers",
    route_class=ProtectedProfileRoute,
    dependencies=[Depends(require_api_token)],
    tags=["Provider research"],
)


class ActorInspect(Contract):
    actor_id: str = Field(min_length=1, max_length=200)


@router.get("/apify")
async def apify_status(session: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    cached = await session.get(OwnerPreference, "apify_capabilities")
    return {
        "provider": "apify",
        "transport": "official_api",
        "local_token_configured": bool(settings.APIFY_API_TOKEN),
        "local_mcp_verified": False,
        "account_rotation": False,
        "budget_key": "apify",
        "monthly_limit_usd": settings.APIFY_MONTHLY_LIMIT_USD,
        "per_run_cap_usd": settings.APIFY_PER_RUN_CAP_USD,
        "linkedin_collection_enabled": False,
        "investigated_actors": list(INVESTIGATED_ACTORS),
        "last_account_inspection": cached.value if cached else None,
    }


@router.post("/apify/inspect")
async def inspect_apify_account(session: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    if not settings.APIFY_API_TOKEN:
        raise HTTPException(409, "apify_local_token_not_configured")
    await (
        session.commit()
    )  # do not hold the runtime pool slot across independent pacing.
    try:
        await claim_access(get_session_factory(), "apify_metadata")
        result = await OfficialApifyAPI(settings.APIFY_API_TOKEN).account_limits()
    except DiscoveryError as exc:
        raise HTTPException(409, str(exc)) from None
    row = await session.get(OwnerPreference, "apify_capabilities", with_for_update=True)
    if row:
        row.value = result
    else:
        session.add(OwnerPreference(key="apify_capabilities", value=result))
    await session.commit()
    return result


@router.post("/apify/actors/inspect")
async def inspect_apify_actor(
    data: ActorInspect, session: AsyncSession = Depends(get_db_session)
):
    settings = get_settings()
    allowed = set(INVESTIGATED_ACTORS) | {
        c.get("actor_id")
        for c in settings.APIFY_SOURCES.values()
        if isinstance(c, dict)
    }
    for routes in settings.APIFY_SOURCE_ROUTES.values():
        allowed.update(c.get("actor_id") for c in routes if isinstance(c, dict))
    if data.actor_id not in allowed:
        raise HTTPException(409, "apify_actor_metadata_not_allowlisted")
    await session.commit()
    try:
        await claim_access(get_session_factory(), "apify_metadata")
        result = await OfficialApifyAPI().actor(data.actor_id)
    except DiscoveryError as exc:
        raise HTTPException(409, str(exc)) from None
    return result
