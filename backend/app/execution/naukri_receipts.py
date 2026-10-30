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
    return {
        "naukri_recorded": recorded,
        "owner_authorized_software_operated_ui": recorded,
        "installed_recurring_worker": 0,
        "employer_acknowledged": 0,
        "records_requiring_review": len(records) - recorded,
        "evidence_source": "retained_operator_observations_of_naukri_application_status_ui",
        "live_reverified_by_this_read": False,
    }


async def prevents_replay(session, requisition):
    # Even damaged/unconfirmed evidence must be reconciled, never retried to
    # repair a counter. Existence fences replay; strict validation above counts.
    await session.flush()
    return await session.get(
        OwnerPreference, PREFIX + requisition, populate_existing=True
    ) is not None
