"""Explicit owner actions against allowlisted Mail accounts; no background watcher."""

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.token_store import ConnectionError
from backend.app.local_agent.apple_mail import AppleMail, Draft

router = APIRouter(prefix="/apple-mail", route_class=ProtectedProfileRoute, dependencies=[Depends(require_api_token)])


def service(session: AsyncSession = Depends(get_db_session)):
    return AppleMail(session, get_settings())


async def operation(call):
    try:
        return await call
    except ConnectionError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/accounts")
async def accounts(svc=Depends(service)):
    return await operation(svc.accounts())


@router.post("/accounts/{account_id}/search")
async def search(account_id: str = Path(min_length=1, max_length=128), svc=Depends(service)):
    return await operation(svc.search(account_id))


@router.post("/accounts/{account_id}/messages/{message_id}/read")
async def read(account_id: str = Path(min_length=1, max_length=128), message_id: int = Path(ge=0), svc=Depends(service)):
    return await operation(svc.read(account_id, message_id))


@router.post("/accounts/{account_id}/drafts")
async def draft(data: Draft, account_id: str = Path(min_length=1, max_length=128), svc=Depends(service)):
    return await operation(svc.draft(account_id, data))
