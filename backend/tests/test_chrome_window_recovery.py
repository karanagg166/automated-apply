"""Windowless heartbeats cannot become application or window-creation grants."""

import pytest

from backend.app.browser import chrome_profiles as profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.naukri_identity import KEY
from backend.app.execution.queue_contracts import QueueControl
from backend.app.local_agent.contracts import Command
from backend.app.local_agent.service import dispatch
from backend.tests.test_chrome_profiles import ACTOR, settings
from backend.tests.test_naukri_background_queue import setup


@pytest.mark.parametrize("change", [None, "stop", "off", "unselected", "unapproved", "consent"])
async def test_window_recovery_requires_current_policy_and_approved_binding(db_session, phase2_profile, change):
    context = await setup(db_session, browser_search=True)
    if change == "stop":
        config = await queue.configuration(db_session)
        await queue.control(db_session, QueueControl(action="stop", expected_revision=config["revision"]))
    elif change == "off":
        await queue.put(db_session, "exec_config:naukri", {"mode": "OFF"})
    elif change == "unselected":
        config = await profiles.selection(db_session)
        await profiles.select_profile(db_session, profiles.ProfileSelection(expected_version=config["version"], profile_binding_id=None))
    elif change == "unapproved":
        await db_session.delete(await db_session.get(OwnerPreference, KEY))
    empty = {**context, "window_id": None}
    result = await dispatch(db_session, settings(), ACTOR, Command(
        command="heartbeat_chrome_profile", profile_commands_enabled=change != "consent", **empty,
    ))
    assert result.ok, result.error_code
    assert result.data["background_window_allowed"] is (change is None)
    assert result.data["profile"]["status"] == "PROFILE_OFFLINE"
    denied = await dispatch(db_session, settings(), ACTOR, Command(command="poll_chrome_command", **empty))
    assert not denied.ok and denied.error_code == "PROFILE_OFFLINE"
    assert await queue.items(db_session) == []
    if change is None:
        restored = await dispatch(db_session, settings(), ACTOR, Command(
            command="heartbeat_chrome_profile", profile_commands_enabled=True, **(context | {"window_id": 20}),
        ))
        assert restored.ok and restored.data["profile"]["status"] == "CONNECTED"
        assert restored.data["profile"]["window_id"] == 20
        assert "background_window_allowed" not in restored.data


async def test_bad_binding_cannot_request_a_recovery_window(db_session, phase2_profile):
    context = await setup(db_session, browser_search=True)
    result = await dispatch(db_session, settings(), ACTOR, Command(
        command="heartbeat_chrome_profile", profile_commands_enabled=True,
        **(context | {"window_id": None, "profile_secret": "0" * 64}),
    ))
    assert not result.ok and result.error_code == "PROFILE_OFFLINE"
