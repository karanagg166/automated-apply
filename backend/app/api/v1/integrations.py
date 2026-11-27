"""Owner APIs plus a browser-bound, durable-state Google OAuth callback."""

import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.registry import connector_registry
from backend.app.integrations.token_store import ConnectionError

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])
COOKIE = "gmail_oauth_browser"
CALLBACK = "/api/v1/integrations/gmail/oauth/callback"


class ConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_email: EmailStr | None = None
    authorization_mode: Literal["metadata", "compose"] = "metadata"


def connection_service(session: AsyncSession = Depends(get_db_session)):
    return ConnectionService(session)


@router.get("", dependencies=[Depends(require_api_token)])
async def integrations(session: AsyncSession = Depends(get_db_session)):
    return await connector_registry(session)


@router.post("/gmail/connect/start", dependencies=[Depends(require_api_token)])
async def start(
    data: ConnectInput, response: Response, service=Depends(connection_service)
):
    browser = secrets.token_urlsafe(32)
    try:
        result = await service.start(
            str(data.expected_email) if data.expected_email else None, browser,
            **({"compose": True} if data.authorization_mode == "compose" else {})
        )
    except ConnectionError as exc:
        if str(exc) == "gmail_compose_schema_update_required":
            raise HTTPException(409,
                "Gmail draft authorization needs an operator setup update. Your existing account identity remains connected.") from None
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
    cookie = COOKIE
    try:
        if state.startswith("mailbox."):
            from backend.app.integrations.gmail.mailboxes import Mailboxes
            parts = state.split(".")
            if len(parts) != 3 or parts[1] not in {"1", "2"}:
                raise ConnectionError("invalid_oauth_state_or_redirect")
            cookie = "gmail54_oauth_" + parts[1]
            service = Mailboxes(service.session, service.settings)
        elif state.startswith("draft."):
            from backend.app.integrations.gmail.drafts import DraftAccountService
            service = DraftAccountService(service.session, service.settings)
        result = await service.callback(
            state, request.cookies.get(cookie), callback_uri, code, error
        )
    except ConnectionError as exc:
        raise HTTPException(400, str(exc)) from None
    response.delete_cookie(cookie, path=CALLBACK)
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


# Read-only accounts use the existing browser-bound callback and token lifecycle.
from uuid import UUID

from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.integrations.gmail.read_service import (
    GmailReadService,
    LeadImport,
    ReadConnect,
    ReadPolicy,
)

read_router = APIRouter(prefix="/gmail/accounts", route_class=ProtectedProfileRoute,
                        dependencies=[Depends(require_api_token)])


def read_service(session: AsyncSession = Depends(get_db_session)):
    return GmailReadService(session, get_settings())


@read_router.get("")
async def gmail_read_accounts(service=Depends(read_service)):
    try:
        return {"accounts": await service.accounts(), "workflow": "readonly", "schema_ready": True}
    except ConnectionError as exc:
        if str(exc) == "gmail_readonly_schema_update_required":
            return {"accounts": [], "workflow": "readonly", "schema_ready": False, "error_code": str(exc)}
        raise HTTPException(409, str(exc)) from None


@read_router.post("/connect/start")
async def gmail_read_connect(data: ReadConnect, response: Response, session: AsyncSession = Depends(get_db_session)):
    browser = secrets.token_urlsafe(32)
    settings = get_settings()
    try:
        result = await ConnectionService(session, read_only=True).start(str(data.expected_email) if data.expected_email else None, browser, read_body=data.read_body)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None
    response.set_cookie(COOKIE, browser, max_age=settings.OAUTH_STATE_TTL_SECONDS, httponly=True,
                        secure=bool(settings.GMAIL_REDIRECT_URI and settings.GMAIL_REDIRECT_URI.startswith("https:")),
                        samesite="lax", path=CALLBACK)
    return result


@read_router.get("/{account_id}")
async def gmail_read_status(account_id: UUID, service=Depends(read_service)):
    try:
        return await service.status(account_id)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.put("/{account_id}/selection")
async def gmail_read_selection(account_id: UUID, data: ReadPolicy, service=Depends(read_service)):
    try:
        return await service.configure(account_id, data)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.post("/{account_id}/sync")
async def gmail_read_sync(account_id: UUID, service=Depends(read_service)):
    try:
        return await service.sync(account_id)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.get("/{account_id}/evidence")
async def gmail_read_evidence(account_id: UUID, offset: int = Query(0, ge=0, le=100000),
                              limit: int = Query(25, ge=1, le=100), service=Depends(read_service)):
    try:
        return {"evidence": await service.evidence(account_id, offset, limit), "offset": offset, "limit": limit}
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.post("/{account_id}/verify")
async def gmail_read_verify(account_id: UUID, service=Depends(read_service)):
    try:
        await service.connection(account_id).verify()
        return await service.status(account_id)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.post("/{account_id}/disconnect")
async def gmail_read_disconnect(account_id: UUID, service=Depends(read_service)):
    try:
        return await service.disconnect(account_id)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.get("/{account_id}/leads")
async def gmail_read_leads(account_id: UUID, offset: int = Query(0, ge=0, le=100000),
                           limit: int = Query(25, ge=1, le=100), service=Depends(read_service)):
    try:
        return {"leads": await service.leads(account_id, offset, limit), "offset": offset, "limit": limit}
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@read_router.post("/{account_id}/evidence/{evidence_id}/import")
async def gmail_read_import(account_id: UUID, evidence_id: str, data: LeadImport, service=Depends(read_service)):
    try:
        return await service.import_lead(account_id, evidence_id, data)
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


router.include_router(read_router)

from backend.app.integrations.gmail.workspace import router as workspace_router

router.include_router(workspace_router)

from backend.app.integrations.gmail.mailboxes_router import (
    router as local_mailboxes_router,
)

router.include_router(local_mailboxes_router)

# Milestone 2: the /integrations/apple-mail/* routes were removed (no dashboard caller); the AppleMail
# service stays for `backend/scripts/local_mail.py` and the v2 Mail.app draft bridge.
