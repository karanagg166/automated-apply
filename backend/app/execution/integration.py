"""Lazy boundary for historical packet-only installations.

Do not register command/worker models in older migration or offline processes
unless an actual execution intent belongs to the packet.
"""

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.knowledge.missing_input import storage_available


async def lock_packet_execution(session, packet_id):
    if not await storage_available(session):
        return None
    exists = await session.scalar(
        select(OwnerPreference.key)
        .where(
            OwnerPreference.key.startswith("exec:"),
            OwnerPreference.value["packet_id"].as_string() == str(packet_id),
        )
        .limit(1)
    )
    if not exists:
        return None
    from backend.app.execution.store import lock_packet_execution as lock

    return await lock(session, packet_id)
