"""Owner-only, explicitly invoked local Gmail reads and draft tests."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.config import get_settings
from backend.app.core.security import owner_ui, require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.gmail.job_alerts import RETIRED, AlertPolicy
from backend.app.integrations.gmail.mailboxes import (
    Consent,
    Generation,
    Mailboxes,
    ReviewedDraft,
    Search,
    Slot,
)
from backend.app.integrations.token_store import ConnectionError

router = APIRouter(prefix="/gmail/local", route_class=ProtectedProfileRoute, dependencies=[Depends(require_api_token)])


def service(session: AsyncSession = Depends(get_db_session)):
    return Mailboxes(session, get_settings())


async def operation(call):
    try:
        return await call
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/accounts")
async def accounts(svc=Depends(service)):
    from backend.app.integrations.gmail.job_alerts import status

    slots = ("1", "2")[:max(1, len(svc.settings.GMAIL_LOCAL_ALLOWED_EMAILS))]
    accounts = [{**await svc.status(slot), "job_alerts": await status(svc.session, slot)} for slot in slots]
    for account in accounts:
        account["permissions"]["monitoring"] = account["job_alerts"]["enabled"]
    return {"accounts": accounts, "sending_enabled": False,
            "monitoring_enabled": any(a["job_alerts"].get("enabled") for a in accounts)}


@router.put("/accounts/{slot}/job-alerts")
async def configure_alerts(slot: Slot, data: AlertPolicy, request: Request):
    # The alert intake fed the retired v1 Naukri execution queue (Phase 9E).
    owner_ui(request)
    raise HTTPException(409, RETIRED)


@router.post("/accounts/{slot}/job-alerts/sync")
async def sync_alerts(slot: Slot, request: Request):
    owner_ui(request)
    raise HTTPException(409, RETIRED)


@router.post("/accounts/{slot}/connect")
async def connect(slot: Slot, data: Consent, response: Response, svc=Depends(service)):
    browser = secrets.token_urlsafe(32)
    result = await operation(svc.start(slot, data, browser))
    response.set_cookie("gmail54_oauth_" + slot, browser, max_age=svc.settings.OAUTH_STATE_TTL_SECONDS,
        httponly=True, secure=svc.settings.GMAIL_REDIRECT_URI.startswith("https:"),
        samesite="lax", path="/api/v1/integrations/gmail/oauth/callback")
    return result


@router.post("/accounts/{slot}/verify")
async def verify(slot: Slot, svc=Depends(service)):
    return await operation(svc.verify(slot))


@router.post("/accounts/{slot}/disconnect")
async def disconnect(slot: Slot, svc=Depends(service)):
    return await operation(svc.disconnect(slot))


@router.post("/accounts/{slot}/search")
async def search(slot: Slot, data: Search, svc=Depends(service)):
    return await operation(svc.search(slot, data))


@router.post("/accounts/{slot}/messages/{message_id}/read")
async def read(slot: Slot, message_id: str, svc=Depends(service)):
    return await operation(svc.read(slot, message_id))


@router.get("/accounts/{slot}/drafts")
async def drafts(slot: Slot, svc=Depends(service)):
    return await operation(svc.drafts(slot))


@router.post("/accounts/{slot}/test-draft")
async def test_draft(slot: Slot, data: Generation, svc=Depends(service)):
    return await operation(svc.self_test_draft(slot, data.expected_generation))


@router.post("/accounts/{slot}/drafts")
async def create_draft(slot: Slot, data: ReviewedDraft, svc=Depends(service)):
    return await operation(svc.create_draft(slot, data))
