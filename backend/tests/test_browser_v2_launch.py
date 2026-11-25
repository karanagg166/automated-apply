from pathlib import Path

import pytest

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.manager import (
    IGNORE_DEFAULT_ARGS,
    BraveBrowserManager,
    RecycleRefused,
    should_block,
)


def test_launch_options_are_headful_locked_screen_safe_and_not_automation():
    options = BraveBrowserManager().launch_options()
    assert options["headless"] is False
    for flag in ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                 "--disable-background-timer-throttling", "--no-first-run", "--no-default-browser-check"):
        assert flag in options["args"]
    assert "--enable-automation" not in options["args"]
    assert options["ignore_default_args"] == ["--enable-automation"] == list(IGNORE_DEFAULT_ARGS)
    assert options["executable_path"].endswith("Brave Browser")


def test_default_profile_is_outside_desktop(monkeypatch):
    monkeypatch.delenv(brave_profile.PROFILE_DIR_VARIABLE, raising=False)
    path = brave_profile.profile_dir()
    assert path == brave_profile.DEFAULT_PROFILE_DIR
    assert str(path).endswith("Library/Application Support/automated-apply/brave")
    assert Path.home() / "Desktop" not in path.parents
    brave_profile.assert_allowed_location(path)


def test_profile_under_desktop_is_rejected(monkeypatch):
    monkeypatch.setenv(brave_profile.PROFILE_DIR_VARIABLE, str(Path.home() / "Desktop/brave"))
    with pytest.raises(brave_profile.ProfileError, match="protected_folder"):
        brave_profile.ensure_profile_dir()


def test_profile_dir_created_private(tmp_path, monkeypatch):
    target = tmp_path / "automated-apply" / "brave"
    monkeypatch.setenv(brave_profile.PROFILE_DIR_VARIABLE, str(target))
    created = brave_profile.ensure_profile_dir()
    assert created == target and (target.stat().st_mode & 0o777) == 0o700


def test_live_singleton_lock_is_detected(tmp_path):
    import os
    import socket

    (tmp_path / "SingletonLock").symlink_to(f"{socket.gethostname()}-{os.getpid()}")
    lock = brave_profile.profile_lock(tmp_path)
    assert lock and lock.pid == os.getpid()
    with pytest.raises(brave_profile.ProfileInUse):
        brave_profile.assert_profile_free(tmp_path)


def test_stale_singleton_lock_is_ignored(tmp_path):
    import socket

    (tmp_path / "SingletonLock").symlink_to(f"{socket.gethostname()}-999999")
    assert brave_profile.profile_lock(tmp_path) is None


def test_asset_blocking_keeps_auth_and_captcha():
    assert should_block("https://static.naukri.com/v.mp4", "media")
    assert should_block("https://fonts.gstatic.example/x.woff2", "font")
    assert should_block("https://www.google-analytics.com/collect", "xhr")
    assert not should_block("https://www.naukri.com/jobapi/v4/search", "xhr")
    assert not should_block("https://static.naukri.com/app.js", "script")
    assert not should_block("https://www.google.com/recaptcha/api.js", "script")
    assert not should_block("https://www.gstatic.com/recaptcha/font.woff2", "font")


class FakeContext:
    def __init__(self):
        self.pages = []
        self.closed = False

    async def route(self, *_):
        return None

    async def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True


class FakePage:
    def __init__(self, context):
        self.context = context
        self._closed = False

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True
        self.context.pages.remove(self)


class FakePlaywright:
    def __init__(self):
        self.launches = []
        self.chromium = self

    async def start(self):
        return self

    async def stop(self):
        return None

    async def launch_persistent_context(self, user_data_dir, **options):
        self.launches.append((user_data_dir, options))
        context = FakeContext()
        await context.new_page()
        await context.new_page()  # a restored stray tab
        return context


async def test_one_tab_discipline_and_recycle_only_between_jobs(tmp_path):
    fake = FakePlaywright()
    executable = tmp_path / "Brave Browser"
    executable.write_text("")
    manager = BraveBrowserManager(user_data_dir=tmp_path / "brave", executable=executable,
                                  playwright_factory=lambda: fake)
    async with manager.job() as page:
        assert manager._context.pages == [page]
        stray = await manager._context.new_page()
        with pytest.raises(RecycleRefused):
            await manager.recycle()
        assert await manager.maybe_recycle_between_jobs(max_age_sec=0) is False
    assert stray.is_closed()
    assert await manager.maybe_recycle_between_jobs(max_age_sec=0) is True
    assert len(fake.launches) == 2
    assert fake.launches[0][1]["ignore_default_args"] == ["--enable-automation"]
    await manager.close()
