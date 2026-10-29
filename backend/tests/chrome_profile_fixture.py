"""Explicit fictional connection through production dispatch, for native form tests."""

from uuid import UUID

from backend.app.browser.chrome_profiles import (
    PROFILE,
    ProfileSelection,
    select_profile,
    selection,
)
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.service import dispatch

BINDING = {
    "profile_binding_id": UUID("a1111111-1111-4111-8111-111111111111"),
    "profile_secret": "f" * 64,
    "window_id": 10,
}
SESSION = UUID("b1111111-1111-4111-8111-111111111111")


async def connected(session, settings, browser_session_id=SESSION):
    context = {**BINDING, "browser_session_id": browser_session_id}
    if not await session.get(
        OwnerPreference, PROFILE + str(BINDING["profile_binding_id"])
    ):
        result = await dispatch(
            session,
            settings,
            Actor(channel="chrome", identity=settings.CHROME_EXTENSION_ID),
            Command(
                command="connect_chrome_profile",
                profile_label="Fictional Chrome",
                **context,
            ),
        )
        assert result.ok, result.error_code
        current = await selection(session)
        await select_profile(
            session,
            ProfileSelection(
                expected_version=current["version"],
                profile_binding_id=BINDING["profile_binding_id"],
            ),
        )
    return context
