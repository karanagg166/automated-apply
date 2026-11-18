"""Interrupt a named browser command, then reconcile under the existing packet lock."""

import asyncio

from fastapi import HTTPException

from backend.app.browser.runner import browser
from backend.app.browser.service import metadata, status
from backend.app.core.config import get_settings
from backend.app.services.applications.service import ApplicationPacketService


async def cancel(session, packet_id, data):
    service = ApplicationPacketService(session)
    revision = None
    if data.operation_id is None:
        if browser.operations.public(packet_id):
            raise HTTPException(
                409, "Inspect the active operation ID before cancelling it"
            )
        packet = await service.repo.get(packet_id)
        revision = packet.revision
        await session.rollback()
    # A named operation can be fenced before touching the database. Its command
    # may be holding the only connection until browser I/O stops.
    ticket, interrupted = browser.operations.request_stop(
        packet_id, data.operation_id, data.expected_revision, revision
    )
    try:
        async with asyncio.timeout(20):
            await browser.close(packet_id)
            async with browser.lock(packet_id):
                packet = await service.repo.get(packet_id, lock=True)
                from backend.app.browser.adapters import execution_adapter

                if execution_adapter(
                    packet.application_url, get_settings()
                ).submission_enabled:
                    from backend.app.browser.submissions import (
                        attempt_for,
                        finish,
                        revoke,
                    )

                    await revoke(session, packet_id)
                    attempt = await attempt_for(session, packet_id)
                    if attempt and attempt.state != "verified":
                        await finish(
                            session,
                            attempt.id,
                            None,
                            diagnostic="owner_cancelled_after_dispatch_outcome_unknown",
                        )
                saved = await metadata(session, packet_id)
                if saved:
                    saved.value = {
                        **saved.value,
                        "diagnostic": "cancelled",
                        "cancelled_operation": interrupted,
                    }
                service.repo.event(
                    packet,
                    "tracking_updated",
                    packet.lifecycle_state,
                    note="Owner cancelled local browser work; dispatch history and receipts retained",
                )
                await session.commit()
                browser.operations.reconciled(packet_id, ticket)
                return await status(session, packet_id)
    except TimeoutError:
        # Leave admission fenced if shutdown/reconciliation was not proven complete.
        raise HTTPException(
            409,
            "Cancellation requested but reconciliation timed out; inspect status and restart the local runner before new browser work",
        ) from None
