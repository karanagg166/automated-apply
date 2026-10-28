"""Three fixed, independently authorized mailbox roles; no background activation."""

import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, StrictBool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.schemas import Contract
from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.session import get_db_session
from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.gmail.drafts import (
    DraftAccountService,
    DraftApproval,
    DraftInput,
)
from backend.app.integrations.gmail.history import (
    ApplicationHistoryService,
    HistoryReview,
)
from backend.app.integrations.gmail.read_service import GmailReadService
from backend.app.integrations.gmail.schema import require_read_schema
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.connected_account import GmailReadAccount
from backend.app.models.discovery import now

Slot = Literal["read_1", "read_2", "outreach"]
SLOT = "gmail_workspace_slot:"
router = APIRouter(prefix="/gmail/workspace", route_class=ProtectedProfileRoute,
                   dependencies=[Depends(require_api_token)])


class AccountConsent(Contract):
    account_consent: StrictBool
    read_body: StrictBool = False


class Version(Contract):
    expected_version: int = Field(ge=1)


class Retention(Version):
    retention_days: int = Field(ge=14, le=7300)


class Workspace:
    def __init__(self, session, settings=None):
        self.session, self.settings = session, settings or get_settings()

    def drafts(self):
        return DraftAccountService(self.session, self.settings)

    async def accounts(self):
        try:
            await require_read_schema(self.session, self.settings)
        except ConnectionError:
            return {"schema_ready": False, "accounts": [{"slot": slot, "status": "setup_required"}
                    for slot in ("read_1", "read_2", "outreach")], "sending_enabled": False}
        accounts = []
        for slot in ("read_1", "read_2"):
            row = await self.session.get(OwnerPreference, SLOT + slot)
            value = await GmailReadService(self.session, self.settings).status(UUID(row.value["account_id"])) if row else {"status": "not_connected"}
            accounts.append({**value, "slot": slot})
        accounts.append({**await self.drafts().status(), "slot": "outreach"})
        return {"schema_ready": True, "accounts": accounts, "sending_enabled": False}

    async def start(self, slot, consent, browser):
        if not consent.account_consent:
            raise ConnectionError("gmail_account_consent_required")
        await require_read_schema(self.session, self.settings)
        if slot == "outreach":
            if consent.read_body:
                raise ConnectionError("outreach_drafts_only")
            return await self.drafts().start(browser)
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407006,1)"))
        row = await self.session.get(OwnerPreference, SLOT + slot, with_for_update=True, populate_existing=True)
        if row:
            account_id = UUID(row.value["account_id"])
        else:
            account_id = uuid4()
            self.session.add(GmailReadAccount(id=account_id, provider="gmail", google_subject="",
                account_email="pending:" + account_id.hex, status="disconnected", connected_at=now()))
            self.session.add(OwnerPreference(key=SLOT + slot, value={"account_id": str(account_id)}))
            await self.session.commit()
        return await ConnectionService(self.session, self.settings, read_only=True, account_id=account_id).start(
            None, browser, read_body=consent.read_body)


async def workspace(session: AsyncSession = Depends(get_db_session)):
    return Workspace(session)


async def operation(call):
    try:
        return await call
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/accounts")
async def accounts(service=Depends(workspace)):
    return await operation(service.accounts())


@router.post("/accounts/{slot}/connect")
async def connect(slot: Slot, data: AccountConsent, response: Response, service=Depends(workspace)):
    browser = secrets.token_urlsafe(32)
    result = await operation(service.start(slot, data, browser))
    response.set_cookie("gmail_oauth_browser", browser, max_age=service.settings.OAUTH_STATE_TTL_SECONDS,
        httponly=True, secure=service.settings.GMAIL_REDIRECT_URI.startswith("https:"),
        samesite="lax", path="/api/v1/integrations/gmail/oauth/callback")
    return result


@router.post("/outreach/disconnect")
async def disconnect(service=Depends(workspace)):
    return await operation(service.drafts().disconnect())


@router.get("/history")
async def history(service=Depends(workspace)):
    return {"history": await operation(ApplicationHistoryService(service.session).list())}


@router.post("/history/review")
async def review(data: HistoryReview, service=Depends(workspace)):
    return await operation(ApplicationHistoryService(service.session).review(data))


@router.post("/history/{history_id}/forget")
async def forget(history_id: str, data: Version, service=Depends(workspace)):
    return await operation(ApplicationHistoryService(service.session).forget(history_id, data.expected_version))


@router.put("/history/{history_id}/retention")
async def retention(history_id: str, data: Retention, service=Depends(workspace)):
    return await operation(ApplicationHistoryService(service.session).retention(history_id, data.expected_version, data.retention_days))


@router.get("/drafts")
async def drafts(service=Depends(workspace)):
    return {"drafts": await operation(service.drafts().drafts())}


@router.post("/drafts")
async def save_draft(data: DraftInput, service=Depends(workspace)):
    return await operation(service.drafts().save(data))


@router.put("/drafts/{draft_id}")
async def edit_draft(draft_id: str, data: DraftInput, service=Depends(workspace)):
    return await operation(service.drafts().save(data, draft_id))


@router.post("/drafts/{draft_id}/create-in-gmail")
async def create_draft(draft_id: str, data: DraftApproval, service=Depends(workspace)):
    return await operation(service.drafts().create_in_gmail(draft_id, data))
