"""Local-only expiration; never connects to Google or performs mailbox operations."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import update

from backend.app.core.logging import logger
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.history import ApplicationHistoryService


async def sweep(session):
    await session.execute(update(OwnerPreference).where(
        OwnerPreference.key.startswith("gmail_draft_oauth:"),
        OwnerPreference.value["expires_at"].as_string() <= datetime.now(timezone.utc).isoformat()
    ).values(value={"consumed": True, "expired": True}))
    await ApplicationHistoryService(session).list()


async def retention_loop(factory):
    while True:
        try:
            async with factory() as session:
                await sweep(session)
        except Exception:
            logger.error("Gmail local retention sweep failed; no mailbox operation attempted")
        await asyncio.sleep(60)
