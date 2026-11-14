"""Selection cannot silently launch Chrome when Brave is missing."""

import pytest
from fastapi import HTTPException

from backend.app.browser import engine


def test_brave_uses_only_the_installed_explicit_executable(monkeypatch, tmp_path):
    executable = tmp_path / "fictional-brave"
    executable.touch()
    monkeypatch.setitem(engine.BRAVE_EXECUTABLES, engine.sys.platform, str(executable))
    assert engine.launch_options("brave") == {"executable_path": str(executable)}


def test_missing_brave_fails_without_falling_back(monkeypatch):
    monkeypatch.setitem(engine.BRAVE_EXECUTABLES, engine.sys.platform, "/missing/fictional-brave")
    with pytest.raises(HTTPException) as failure:
        engine.launch_options("brave")
    assert failure.value.status_code == 409


@pytest.mark.parametrize("channel", ["msedge", "chromium", "chrome"])
def test_explicit_existing_channels_remain_explicit(channel):
    assert engine.launch_options(channel) == {"channel": channel}


def test_arbitrary_paths_and_safari_cannot_use_chromium_security_options():
    for channel in ("safari", "/tmp/browser", "auto"):
        with pytest.raises(HTTPException) as failure:
            engine.launch_options(channel)
        assert failure.value.status_code == 422
