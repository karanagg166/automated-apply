"""Background mode: the automation Brave never keeps focus away from the owner's app."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from backend.app.browser_v2 import manager as mgr

LSAPPINFO = 'ASN:0x0-0x38ac8a9: (in front)\n    bundleID="com.microsoft.VSCode"\n'


class Recorder:
    def __init__(self, front="ASN:0x0-1", info=LSAPPINFO):
        self.front, self.info, self.calls = front, info, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[:2] == ["/usr/bin/lsappinfo", "front"]:
            return SimpleNamespace(stdout=self.front)
        if cmd[:2] == ["/usr/bin/lsappinfo", "info"]:
            return SimpleNamespace(stdout=self.info)
        return SimpleNamespace(stdout="")


def test_front_bundle_id_parses_lsappinfo_without_permissions():
    run = Recorder()
    assert mgr.front_bundle_id(run) == "com.microsoft.VSCode"
    assert all(c[0] == "/usr/bin/lsappinfo" for c in run.calls)  # no osascript / Apple Events


def test_front_bundle_id_tolerates_failures():
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 3)

    assert mgr.front_bundle_id(boom) is None
    assert mgr.front_bundle_id(Recorder(info="no bundle here")) is None


def test_refocus_uses_open_b_and_never_targets_brave():
    run = Recorder()
    assert mgr.refocus("com.microsoft.VSCode", run) is True
    assert run.calls[-1] == ["/usr/bin/open", "-b", "com.microsoft.VSCode"]
    assert mgr.refocus("com.brave.Browser", run) is False and mgr.refocus(None, run) is False
    assert len(run.calls) == 1


def test_background_mode_switch(monkeypatch):
    monkeypatch.setattr(mgr.sys, "platform", "darwin")
    monkeypatch.delenv(mgr.BACKGROUND_VARIABLE, raising=False)
    assert mgr.background_mode() is True  # default: never steal focus
    monkeypatch.setenv(mgr.BACKGROUND_VARIABLE, "0")
    assert mgr.background_mode() is False
    monkeypatch.setattr(mgr.sys, "platform", "linux")
    monkeypatch.delenv(mgr.BACKGROUND_VARIABLE, raising=False)
    assert mgr.background_mode() is False


async def test_focus_is_handed_back_only_when_brave_took_it(monkeypatch, tmp_path):
    fronts = iter(["com.brave.Browser", "com.microsoft.VSCode", "com.brave.Browser"])
    refocused: list[str] = []
    monkeypatch.setattr(mgr, "front_bundle_id", lambda run=None: next(fronts))
    def fake_refocus(bundle, run=None):
        refocused.append(bundle)
        return True

    monkeypatch.setattr(mgr, "refocus", fake_refocus)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(mgr.asyncio, "sleep", no_sleep)
    await mgr.BraveBrowserManager(user_data_dir=tmp_path)._return_focus("com.microsoft.VSCode")
    assert refocused == ["com.microsoft.VSCode", "com.microsoft.VSCode"]  # 2 of 3 checks saw Brave in front
