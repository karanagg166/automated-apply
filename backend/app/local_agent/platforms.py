"""Public login links and gesture-scoped observations; never a credential store."""
from datetime import datetime, timezone

from backend.app.dashboard.models import OwnerPreference

PLATFORMS = {
    "naukri": ("Naukri", "https://www.naukri.com/nlogin/login"),
    "wellfound": ("Wellfound", "https://wellfound.com/login"),
    "instahyre": ("Instahyre", "https://www.instahyre.com/login/"),
    "work_at_a_startup": ("YC Work at a Startup", "https://www.workatastartup.com/login"),
    "internshala": ("Internshala", "https://internshala.com/login/"),
}


async def platform_connections(session):
    rows = []
    for platform, (name, login_url) in PLATFORMS.items():
        record = await session.get(OwnerPreference, "portal_" + platform)
        value = record.value if record else {}
        rows.append({"platform": platform, "name": name, "login_url": login_url,
            "state": value.get("state", "owner_action_required"),
            "last_verification_time": value.get("last_verification_time"),
            "evidence_type": value.get("evidence_type", "none"),
            "identity_verified": False, "api_connected": False,
            "capabilities": ["manual_handoff", "url_preview", "gesture_session_observation"],
            "submission": "unsupported", "owner_acceptance_required": value.get("manual_capability_accepted") is not True})
    return rows


async def save_observation(session, platform, observation):
    if platform not in PLATFORMS or observation not in {"signed_in_indicator", "login_required", "unverifiable", "forgotten"}:
        raise ValueError("unsupported_platform_observation")
    key = "portal_" + platform
    row = await session.get(OwnerPreference, key, with_for_update=True)
    accepted = bool(row and row.value.get("manual_capability_accepted") is True and observation != "forgotten")
    value = {"state": "browser_session_observed" if observation == "signed_in_indicator" else "manual_only" if accepted else "owner_action_required",
        "last_verification_time": datetime.now(timezone.utc).isoformat() if observation != "forgotten" else None,
        "evidence_type": "extension_gesture_dom_indicator" if observation != "forgotten" else "metadata_forgotten",
        "observation": observation, "manual_capability_accepted": accepted}
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=key, value=value))
    await session.flush()
    return value


async def accept_manual_capability(session, platform):
    if platform not in PLATFORMS:
        raise ValueError("unsupported_platform")
    key = "portal_" + platform
    row = await session.get(OwnerPreference, key, with_for_update=True)
    value = dict(row.value) if row else {}
    value.update(manual_capability_accepted=True,
        manual_capability_accepted_at=datetime.now(timezone.utc).isoformat())
    if value.get("state") != "browser_session_observed":
        value["state"] = "manual_only"
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=key, value=value))
    await session.flush()
    return value
