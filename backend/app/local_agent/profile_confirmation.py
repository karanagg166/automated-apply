"""Owner review is bound to one saved profile version, never inferred from import."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.contracts import StrictModel


class ProfileConfirmation(StrictModel):
    expected_version: int = Field(ge=1)
    owner_confirmed: Literal[True]


async def confirm_profile(session, profile, expected_version):
    if not profile or profile.version != expected_version:
        raise ValueError("profile_changed_review_current_version")
    row = await session.get(OwnerPreference, "phase1_profile_confirmation", with_for_update=True)
    was_current = confirmation_matches(profile, row.value if row else {})
    value = {"profile_id": str(profile.id), "profile_version": profile.version,
        "confirmed_at": datetime.now(timezone.utc).isoformat()}
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key="phase1_profile_confirmation", value=value))
    await session.flush()
    if not was_current:
        from backend.app.execution.queue_reconsideration import request

        await request(session, "owner_profile_version_confirmed")
    return value


def confirmation_matches(profile, value):
    return bool(profile and value.get("profile_id") == str(profile.id)
        and value.get("profile_version") == profile.version and value.get("confirmed_at"))
