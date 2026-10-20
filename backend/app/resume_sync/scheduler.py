"""A real, opt-in, bounded worker loop. Nothing starts at API startup."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.resume_sync.models import ResumeDriveSource
from backend.app.resume_sync.service import ResumeSyncService
from backend.app.services.discovery_budget import insert_for


async def tick(session_factory, settings, *, heartbeat=False):
    # Heartbeat commits independently, so a bounded slow download does not erase it.
    if heartbeat:
        async with session_factory() as session, session.begin():
            expiry = datetime.now(timezone.utc) + timedelta(seconds=150)
            value = {"expires_at": expiry.isoformat()}
            await session.execute(insert_for(session)(OwnerPreference).values(
                key="resume_drive_scheduler", value=value,
            ).on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    async with session_factory() as session, session.begin():
        source = await session.scalar(select(ResumeDriveSource).where(ResumeDriveSource.key == "primary"))
        # Opt-in must be durably saved by the owner; an env flag never starts work.
        if source is None or not source.sync_enabled:
            return "disabled"
        result = await ResumeSyncService(session, settings).sync(scheduled=True)
        return result["outcome"]


async def serve(session_factory, settings, stop: asyncio.Event):
    while not stop.is_set():
        await tick(session_factory, settings, heartbeat=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            continue
    async with session_factory() as session, session.begin():
        item = await session.get(OwnerPreference, "resume_drive_scheduler")
        if item:
            item.value = {}
