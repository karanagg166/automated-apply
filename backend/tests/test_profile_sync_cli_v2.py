"""Phase 9D CLI: sync-profile (dry-run default, typed live confirmation, profile-lock refusal) and
probe-profile-page (PII-scrubbed outline). Fakes only: never a real browser, portal or DB."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import pytest

from backend.app.browser_v2 import cli
from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.cli.commands_profile import (
    probe_profile_command,
    sync_profile_command,
)
from backend.app.browser_v2.profile_sync.probe import capture_outline, outline
from backend.app.browser_v2.store import MemoryStore


class FakePage:
    url = "about:blank"

    def __init__(self) -> None:
        self.visited: list[str] = []

    async def goto(self, url: str, **_: Any) -> None:
        self.visited.append(url)

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if arg is None:
            return ["Profile summary", "Key skills", "Call me at +91 98765 43210"]
        return {"url": "https://www.naukri.com/mnjuser/profile?token=abc", "title": "Profile",
                "headings": ["Resume headline", "Jane Example"],
                "buttons": [{"tag": "button", "text": "Save", "id": "saveKeySkills"}],
                "inputs": [{"tag": "input", "type": "text", "id": "keySkillSugg", "value": "SECRET-VALUE"}],
                "snippets": ["jane@example.com earns 12 LPA"],
                "selector_matches": {"key_skills.input": {"count": 1, "visible": True}}}


class FakeManager:
    def __init__(self) -> None:
        self.page = FakePage()
        self.jobs = 0
        self.closed = False

    @asynccontextmanager
    async def job(self):
        self.jobs += 1
        yield self.page

    async def close(self) -> None:
        self.closed = True


class FakeService:
    def __init__(self) -> None:
        self.store = MemoryStore(profile={"full_name": "Jane Example", "preferences": {"summary": "Hello"}})
        self.manager = FakeManager()
        self.adapters: dict[str, Any] = {}
        self.env_profile: dict[str, str] = {}


def factory_for(service: FakeService, backend: str = "postgres"):
    async def factory(*, require_db: bool):
        factory.calls.append(require_db)  # type: ignore[attr-defined]
        return service, backend
    factory.calls = []  # type: ignore[attr-defined]
    return factory


def free() -> None:
    return None


def held() -> None:
    raise brave_profile.ProfileInUse("Brave is already using the profile (pid 42)")


def test_parser_defaults_to_dry_run_and_dispatches(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake(portal: str, live: bool, yes: bool) -> int:
        seen.update(portal=portal, live=live, yes=yes)
        return 0

    monkeypatch.setattr(cli, "sync_profile_command", fake)
    assert cli.main(["sync-profile", "--portal", "naukri"]) == 0
    assert seen == {"portal": "naukri", "live": False, "yes": False}
    assert cli.main(["sync-profile", "--portal", "naukri", "--dry-run"]) == 0 and seen["live"] is False
    with pytest.raises(SystemExit):
        cli.main(["sync-profile", "--portal", "naukri", "--dry-run", "--confirm-live"])
    with pytest.raises(SystemExit):
        cli.main(["sync-profile", "--portal", "greenhouse"])


async def test_dry_run_runs_without_db_and_writes_nothing(capsys):
    service = FakeService()
    factory = factory_for(service, backend="memory")
    assert await sync_profile_command("naukri", service_factory=factory, lock_check=free) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["dry_run"] is True and out["status"] == "skipped"
    assert factory.calls == [False] and service.manager.jobs == 0 and service.manager.closed
    assert "Hello" not in json.dumps(out)


async def test_live_requires_typed_confirmation(capsys):
    service = FakeService()
    factory = factory_for(service)
    assert await sync_profile_command("naukri", True, service_factory=factory, lock_check=free,
                                      input_fn=lambda _: "SYNC wellfound", is_tty=True) == 2
    assert "confirmation_mismatch" in capsys.readouterr().out
    assert await sync_profile_command("naukri", True, service_factory=factory, lock_check=free, is_tty=False) == 2
    assert "typed_confirmation" in capsys.readouterr().out
    assert factory.calls == []  # refused before any service/browser is built
    assert await sync_profile_command("naukri", True, service_factory=factory_for(service, "memory"),
                                      lock_check=free, input_fn=lambda _: "SYNC naukri", is_tty=True) == 2
    assert "live_requires_postgres_store" in capsys.readouterr().out
    assert await sync_profile_command("naukri", True, service_factory=factory, lock_check=free,
                                      input_fn=lambda _: "SYNC naukri", is_tty=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "live" and out["dry_run"] is True  # profile_sync.naukri.live is off
    assert out["receipt"]["live_blocked"] == "profile_sync_live_flag_off" and factory.calls == [True]


async def test_both_commands_refuse_while_the_brave_profile_is_in_use(capsys, monkeypatch):
    factory = factory_for(FakeService())
    assert await sync_profile_command("naukri", service_factory=factory, lock_check=held) == 2
    assert "already using" in capsys.readouterr().out
    assert await probe_profile_command("naukri", service_factory=factory, lock_check=held) == 2
    assert "already using" in capsys.readouterr().out
    monkeypatch.setattr(brave_profile, "assert_profile_free", held)  # the default lock check
    assert await sync_profile_command("naukri", service_factory=factory) == 2
    assert factory.calls == []


async def test_probe_needs_a_url_where_none_is_verified(capsys):
    factory = factory_for(FakeService())
    assert await probe_profile_command("wellfound", service_factory=factory, lock_check=free) == 2
    assert "--url" in capsys.readouterr().out and factory.calls == []


async def test_probe_writes_a_scrubbed_outline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(brave_profile.PROFILE_DIR_VARIABLE, str(tmp_path / "brave"))
    service = FakeService()
    assert await probe_profile_command("naukri", service_factory=factory_for(service), lock_check=free) == 0
    result = json.loads(capsys.readouterr().out)
    assert service.manager.page.visited == ["https://www.naukri.com/mnjuser/profile"] and service.manager.closed
    text = (tmp_path / "receipts" / "profile-probe").joinpath(result["outline"].rsplit("/", 1)[1]).read_text()
    payload = json.loads(text)
    assert payload["kind"] == "profile_page_outline" and "Profile summary" in payload["labels"]
    for secret in ("SECRET-VALUE", "Jane Example", "98765", "jane@example.com", "token=abc"):
        assert secret not in text
    assert payload["inputs"][0]["id"] == "keySkillSugg" and "snippets" not in payload


async def test_outline_and_https_only(tmp_path):
    from backend.app.browser_v2.profile_sync.probe import ProbeRefused

    with pytest.raises(ProbeRefused):
        await capture_outline(FakePage(), "naukri", object(), "http://insecure.example", root=tmp_path)
    data = outline({"headings": ["Key skills"]}, ["Email jane.doe@gmail.com"], "naukri", ())
    assert "jane.doe@gmail.com" not in json.dumps(data)
