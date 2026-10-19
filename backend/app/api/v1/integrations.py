"""Owner APIs plus a browser-bound, durable-state Google OAuth callback."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.registry import connector_registry
from backend.app.integrations.token_store import ConnectionError
from backend.app.mcp.registry import mcp_status

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])
COOKIE = "gmail_oauth_browser"
CALLBACK = "/api/v1/integrations/gmail/oauth/callback"


class ConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_email: EmailStr | None = None


def connection_service(session: AsyncSession = Depends(get_db_session)):
    return ConnectionService(session)


@router.get("", dependencies=[Depends(require_api_token)])
async def integrations(session: AsyncSession = Depends(get_db_session)):
    return await connector_registry(session)


@router.get("/mcp/status", dependencies=[Depends(require_api_token)])
async def mcp_integration_status():
    return mcp_status()


@router.post("/gmail/connect/start", dependencies=[Depends(require_api_token)])
async def start(
    data: ConnectInput, response: Response, service=Depends(connection_service)
):
    browser = secrets.token_urlsafe(32)
    try:
        result = await service.start(
            str(data.expected_email) if data.expected_email else None, browser
        )
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None
    settings = get_settings()
    response.set_cookie(
        COOKIE,
        browser,
        max_age=settings.OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=bool(
            settings.GMAIL_REDIRECT_URI
            and settings.GMAIL_REDIRECT_URI.startswith("https:")
        ),
        samesite="lax",
        path=CALLBACK,
    )
    return result


@router.get("/gmail/oauth/callback")
async def callback(
    request: Request,
    response: Response,
    state: str = Query(..., min_length=32, max_length=128),
    code: str | None = Query(None, max_length=4096),
    error: str | None = Query(None, max_length=100),
    service=Depends(connection_service),
):
    if any(
        len(request.query_params.getlist(k)) > 1 for k in ("state", "code", "error")
    ):
        raise HTTPException(400, "ambiguous_oauth_callback")
    callback_uri = str(request.url.replace(query=""))
    try:
        result = await service.callback(
            state, request.cookies.get(COOKIE), callback_uri, code, error
        )
    except ConnectionError as exc:
        raise HTTPException(400, str(exc)) from None
    response.delete_cookie(COOKIE, path=CALLBACK)
    return {"status": "connected", "connection": result}


@router.get("/gmail/status", dependencies=[Depends(require_api_token)])
async def gmail_status(service=Depends(connection_service)):
    return await service.status()


@router.post("/gmail/verify", dependencies=[Depends(require_api_token)])
async def verify(service=Depends(connection_service)):
    try:
        await service.verify()
        return await service.status()
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/gmail/disconnect", dependencies=[Depends(require_api_token)])
async def disconnect(service=Depends(connection_service)):
    return await service.disconnect()
