"""Transactional preparation notices. No portal actions or message transport."""

import hashlib

from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    OwnerPreference,
)
from backend.app.services.applications.service import TERMINAL
from backend.app.services.discovery_budget import insert_for


async def notify_packet(session, execution, packet):
    """Announce saved answers and manual handoff separately from submission.

    Callers hold the execution/owner fence. A durable conflict key prevents
    duplicate notices across retries/restarts; notices commit with the packet.
    Unknown/expired answers, changed context and Stop never announce readiness.
    """
    if (
        packet.platform != "naukri"
        or packet.readiness.stale
        or packet.lifecycle_state in TERMINAL
        or packet.readiness.state not in {"needs_review", "ready_for_manual_handoff"}
        or not packet.snapshot.destination.valid
    ):
        return False
    if execution:
        from backend.app.execution import store

        if (execution.value["platform"] != "naukri"
                or execution.value["state"] in store.TERMINAL | {"PAUSED"}
                or execution.value.get("cancelled")):
            return False
    # Packet-only owner review must not import command/worker models into
    # historical packet installations. These two policies live in owner storage.
    automation_row = await session.get(OwnerPreference, "naukri_automation", populate_existing=True)
    automation = automation_row.value if automation_row else {"revision": 0, "state": "STOPPED"}
    configuration = await session.get(OwnerPreference, "exec_config:naukri", populate_existing=True)
    if ((automation.get("revision") and automation["state"] != "RUNNING")
            or (configuration and configuration.value.get("mode") == "OFF")):
        return False
    from backend.app.dashboard.notifications import preferences

    prefs = await preferences(session)
    if prefs.paused or not prefs.in_app:
        return False
    # needs_review may mean stale facts or unresolved required fields. Use the
    # same readiness calculation as approval, without approving any field.
    from backend.app.services.applications.eligibility import readiness

    candidate = readiness(packet.snapshot, packet.fields, approved=True)
    if candidate.state not in {"needs_review", "ready_for_manual_handoff"}:
        return False
    approved = packet.readiness.state == "ready_for_manual_handoff"
    if approved and packet.approved_revision != packet.revision:
        return False
    phase = "manual_handoff" if approved else "owner_review"
    key = f"naukri-packet:{packet.id}:{packet.revision}:{phase}"
    title = "Naukri application ready for " + ("manual Apply" if approved else "owner review")
    body = (
        f"{packet.snapshot.job_title} at {packet.snapshot.company_name or 'saved employer'}. "
        f"Packet revision {packet.revision}: saved resume and answers "
        + ("reviewed. " if approved else "prepared; review required. ")
        + "Verify the live vacancy, saved Naukri resume and any actual questions. "
        "Apply is owner-operated and may submit immediately or follow the company. "
        "No application has been sent."
    )
    result = await session.execute(insert_for(session)(Notification).values(
        dedup_key=key, kind="application_ready", title=title, body=body,
        href="/applications/" + str(packet.id),
    ).on_conflict_do_nothing(index_elements=[Notification.dedup_key]).returning(Notification.id))
    notification_id = result.scalar_one_or_none()
    if notification_id is None:
        return False
    await session.execute(insert_for(session)(NotificationDelivery).values(
        notification_id=notification_id, channel="in_app", status="available_in_app", attempt_count=1,
    ).on_conflict_do_nothing(index_elements=["notification_id", "channel"]))
    # Reuse only the existing explicitly selected owner channel. Merely having
    # bot credentials does not opt a preparation policy into Telegram notices.
    policy = automation.get("policy") or {}
    if (execution and automation["state"] == "RUNNING"
            and execution.value.get("automation_revision") == automation["revision"]
            and policy.get("telegram_questions")):
        from backend.app.core.config import get_settings
        from backend.app.local_agent.models import TelegramDelivery

        settings = get_settings()
        if (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_OWNER_CHAT_ID
                and settings.TELEGRAM_OWNER_USER_ID):
            delivery_id = -int(hashlib.sha256(key.encode()).hexdigest()[:15], 16) - (1 << 61)
            await session.execute(insert_for(session)(TelegramDelivery).values(
                update_id=delivery_id, state="pending",
                reply=title + ": " + body + " Open Automated Apply → Applications → " + str(packet.id),
            ).on_conflict_do_nothing(index_elements=[TelegramDelivery.update_id]))
    return True
