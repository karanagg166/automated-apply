"""Portal logins survive closing/reopening Brave: profile prefs + portal session-cookie vault."""

from __future__ import annotations

import json
import os

from backend.app.browser_v2 import profile as bp
from backend.app.browser_v2.manager import (
    SESSION_COOKIE_FILE,
    BraveBrowserManager,
    is_portal_cookie,
)


def test_preferences_enforce_continue_where_left_off_and_no_session_only_cookies(tmp_path):
    prefs = tmp_path / "Default/Preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({"session": {"restore_on_startup": 5}, "browser": {"clear_data_on_exit": True},
                                 "profile": {"default_content_setting_values": {"cookies": 4}, "exit_type": "Normal"}}))
    changed = bp.ensure_persistent_preferences(tmp_path)
    data = json.loads(prefs.read_text())
    assert data["session"]["restore_on_startup"] == 1 and data["browser"]["clear_data_on_exit"] is False
    assert "cookies" not in data["profile"]["default_content_setting_values"]
    assert data["profile"]["exit_type"] == "Normal"  # unrelated prefs untouched
    assert set(changed) == {"session.restore_on_startup", "profile.default_content_setting_values.cookies",
                            "browser.clear_data_on_exit"}
    assert bp.ensure_persistent_preferences(tmp_path) == {}  # idempotent


def test_fresh_profile_gets_the_preference_file(tmp_path):
    assert bp.ensure_persistent_preferences(tmp_path) == {"session.restore_on_startup": 1}
    assert json.loads((tmp_path / "Default/Preferences").read_text())["session"]["restore_on_startup"] == 1


def test_only_portal_cookies_are_persisted():
    assert is_portal_cookie({"domain": ".naukri.com"}) and is_portal_cookie({"domain": "account.ycombinator.com"})
    assert not is_portal_cookie({"domain": ".google.com"}) and not is_portal_cookie({"domain": "evilnaukri.com"})


class FakeContext:
    def __init__(self, cookies):
        self.jar = list(cookies)

    async def cookies(self):
        return list(self.jar)

    async def add_cookies(self, cookies):
        self.jar.extend(cookies)


async def test_snapshot_then_restore_after_restart(tmp_path):
    session = {"name": "sid", "value": "TEST_FAKE_TOKEN_ONLY", "domain": ".instahyre.com", "path": "/",
               "expires": -1, "secure": True, "httpOnly": True, "sameSite": "Lax"}
    persistent = {**session, "name": "keep", "expires": 9_999_999_999}
    other = {**session, "name": "g", "domain": ".google.com"}
    first = BraveBrowserManager(user_data_dir=tmp_path)
    first._context = FakeContext([session, persistent, other])
    assert await first.snapshot_session_cookies() == 1  # only the portal SESSION cookie
    stored = tmp_path / SESSION_COOKIE_FILE
    assert oct(os.stat(stored).st_mode & 0o777) == "0o600"
    second = BraveBrowserManager(user_data_dir=tmp_path)
    second._context = FakeContext([persistent])  # restart dropped the session cookie
    assert await second.restore_session_cookies() == 1
    assert {c["name"] for c in second._context.jar} == {"keep", "sid"}
    assert await second.restore_session_cookies() == 0  # never duplicates or overwrites live cookies
