"""Read retained provider-UI observations without rewriting their provenance.

These are operator observations, not an automated verification adapter or an
employer acknowledgment. No browser action, receipt import or dispatch lives here.
"""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference

PREFIX = "naukri_receipt:"


def recorded_application(key, value, now):
    """Only exact, persistent Application Status observations count as sent."""
    if not isinstance(value, dict):
        return False
    requisition = key.removeprefix(PREFIX)
    if (
        not key.startswith(PREFIX)
        or not re.fullmatch(r"[0-9]{10,20}", requisition)
        or value.get("requisition") != requisition
        or value.get("confirmation_source") != "naukri_application_status_ui"
        or value.get("operation_mode") != "owner_authorized_software_operated_ui"
        or value.get("status") != "Application Sent"
        or value.get("persistent_after_reload") is not True
        or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("private_evidence_sha256", "")))
    ):
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        return observed.tzinfo is not None and observed <= now + timedelta(minutes=5)
    except (KeyError, ValueError, TypeError):
        return False


async def summary(session):
    await session.flush()
    records = (await session.scalars(
        select(OwnerPreference).where(OwnerPreference.key.startswith(PREFIX))
        .execution_options(populate_existing=True)
    )).all()
    now = datetime.now(timezone.utc)
    recorded = sum(recorded_application(row.key, row.value, now) for row in records)
    workers = (await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith("naukri_worker_receipt:")
    ).execution_options(populate_existing=True))).all()
    verified = [r for r in workers if worker_recorded(r.key, r.value, now)]
    dispatched = sum(r.value.get("worker_dispatched") is True for r in verified)
    return {
        "naukri_recorded": recorded + len(verified),
        "owner_authorized_software_operated_ui": recorded,
        "installed_recurring_worker": dispatched,
        "reconciled_provider_history": len(verified) - dispatched,
        "employer_acknowledged": 0,
        "records_requiring_review": len(records) - recorded + len(workers) - len(verified),
        "evidence_source": "retained_operator_observations_of_naukri_application_status_ui",
        "live_reverified_by_this_read": False,
    }


def worker_recorded(key, value, now):
    if not isinstance(value, dict) or not key.startswith("naukri_worker_receipt:"):
        return False
    requisition = key.removeprefix("naukri_worker_receipt:")
    if (not re.fullmatch(r"[0-9]{10,20}", requisition) or value.get("requisition") != requisition
            or value.get("confirmation_source") != "naukri_application_status_ui"
            or value.get("operation_mode") != "recurring_worker_ui"
            or value.get("persistent_after_reload") is not True or value.get("status") != "Application Sent"
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("account_sha256", "")))):
        return False
    try:
        first, second = value["first_observation"], value["second_observation"]
        observed, original = datetime.fromisoformat(value["observed_at"]), datetime.fromisoformat(first["observed_at"])
        return bool(
            first["document_id"] != second["document_id"]
            and re.fullmatch(r"[a-f0-9]{64}", first["evidence_sha256"])
            and re.fullmatch(r"[a-f0-9]{64}", second["evidence_sha256"])
            and second["state"] == "APPLICATION_SENT"
            and second["account_sha256"] == value["account_sha256"]
            and observed.tzinfo is not None and original.tzinfo is not None
            and original < observed <= now + timedelta(minutes=5)
        )
    except (KeyError, TypeError, ValueError):
        return False


async def prevents_replay(session, requisition):
    # Even damaged/unconfirmed evidence must be reconciled, never retried to
    # repair a counter. Existence fences replay; strict validation above counts.
    await session.flush()
    retained = await session.get(
        OwnerPreference, PREFIX + requisition, populate_existing=True
    )
    worker = await session.get(OwnerPreference, "naukri_worker_receipt:" + requisition, populate_existing=True)
    return retained is not None or worker is not None
