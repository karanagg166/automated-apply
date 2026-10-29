"""Fictional local adapter boundaries. No Mail app or real Chrome is invoked."""

from uuid import uuid4

import pytest

from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.token_store import ConnectionError
from backend.app.local_agent.apple_mail import AppleMail, Draft
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import oauth_settings


@pytest.mark.parametrize("code", ["backend_not_ready", "backend_timeout", "backend_offline", "backend_authentication_failed"])
def test_native_errors_keep_validated_request_identity(tmp_path, monkeypatch, code):
    import io
    import json
    import struct
    from types import SimpleNamespace

    from backend.app.local_agent import native_host
    from backend.app.local_agent.contracts import Command

    settings = oauth_settings(CHROME_EXTENSION_ID="a" * 32)
    path = tmp_path / "private.env"
    path.write_text("")
    path.chmod(0o600)
    command = Command(command="health")
    payload = command.model_dump_json().encode()
    input_stream = io.BytesIO(struct.pack("<I", len(payload)) + payload)
    output_stream = io.BytesIO()
    monkeypatch.setattr("backend.app.operations.configuration.load_settings", lambda _: settings)
    monkeypatch.setattr(native_host.sys, "argv", ["host", str(path), "chrome-extension://" + "a" * 32 + "/"])
    monkeypatch.setattr(native_host.sys, "stdin", SimpleNamespace(buffer=SimpleNamespace(raw=input_stream)))
    monkeypatch.setattr(native_host.sys, "stdout", SimpleNamespace(buffer=output_stream))

    def unavailable(*_):
        raise ValueError(code)

    monkeypatch.setattr(native_host, "forward", unavailable)
    native_host.main()
    frame = output_stream.getvalue()
    assert struct.unpack("<I", frame[:4])[0] == len(frame) - 4
    result = json.loads(frame[4:])
    assert result == {"version": 1, "ok": False, "error_code": code, "request_id": str(command.request_id)}


def mail_settings(**values):
    return oauth_settings(APPLE_MAIL_ENABLED=True, APPLE_MAIL_ACCOUNT_POLICIES={"account1": {
        "address": "owner@example.org", "inbox_mailbox": "INBOX", "drafts_mailbox": "Drafts",
        "read_authorized": True, "draft_authorized": True, "senders": ["alerts@naukri.com"]}}, **values)


async def test_mail_account_allowlist_separate_permissions_and_selected_reads(db_session):
    calls = []
    async def run(request):
        calls.append(request)
        return {"messages": [{"id": 1, "sender": "alerts@naukri.com.attacker.example", "subject": "spoof"},
            {"id": 2, "sender": "Naukri <alerts@naukri.com>", "subject": "job alert"}]}
    service = AppleMail(db_session, mail_settings(), run)
    with pytest.raises(ConnectionError, match="not_allowed"):
        await service.search("another")
    found = await service.search("account1")
    assert [m["id"] for m in found["messages"]] == [2]
    with pytest.raises(ConnectionError, match="selection"):
        await service.read("account1", 1)
    assert len(calls) == 1


async def test_mail_read_extracts_without_opening_or_storing_private_body(db_session):
    async def run(request):
        value = {"id": 2, "sender": "Naukri <alerts@naukri.com>", "subject": "Job alert", "received_at": now().isoformat()}
        return {"messages": [value]} if request["action"] == "search" else {**value, "body": "private job alert text"}
    service = AppleMail(db_session, mail_settings(), run)
    await service.search("account1")
    result = await service.read("account1", 2)
    assert "body" not in result and result["body_stored"] is False and result["links_opened"] is False


async def test_mail_draft_ambiguity_only_reconciles_on_retry(db_session):
    calls = []
    async def run(request):
        calls.append(request["action"])
        raise ConnectionError("apple_mail_operation_unconfirmed")
    service = AppleMail(db_session, mail_settings(), run)
    data = Draft(request_id=uuid4(), recipient="owner@example.org", subject="Unsent test", body="Fictional local draft", owner_reviewed=True)
    with pytest.raises(ConnectionError):
        await service.draft("account1", data)
    with pytest.raises(ConnectionError):
        await service.draft("account1", data)
    assert calls == ["draft", "verify_draft"]


async def test_mail_defaults_never_start_scripting(db_session):
    async def denied(request):
        pytest.fail("Disabled adapter invoked Apple Mail")
    service = AppleMail(db_session, oauth_settings(), denied)
    assert (await service.accounts())["enabled"] is False
    with pytest.raises(ConnectionError, match="disabled"):
        await service.search("account1")


async def test_online_launcher_status_does_not_take_owner_lock(db_session, monkeypatch):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.browser import profile_launcher

    monkeypatch.setattr(profile_launcher.sys, "platform", "darwin")
    binding = str(uuid4())
    mapping = {"profile_binding_id": binding, "profile_directory": "Profile 8", "automatic_launch_enabled": True,
        "chrome_profile_path": str(Path.home() / "Library/Application Support/Google/Chrome/Profile 8"),
        "verified_via": "owner_selected_chrome_version_page"}
    for key, value in [("chr_fixed_profile", mapping), ("chr_selection", {"profile_binding_id": binding}),
            ("naukri_automation", {"state": "RUNNING"}),
            ("chr_prof:" + binding, {"connected": True, "last_heartbeat": now().isoformat()})]:
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()

    async def forbidden(*_, **__):
        pytest.fail("Online status must neither acquire the owner lock nor invoke a process")

    monkeypatch.setattr(profile_launcher, "memory_row", forbidden)
    result = await profile_launcher.ensure_fixed_profile(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        settings=oauth_settings(CHROME_FIXED_PROFILE_LAUNCH_ENABLED=True), run=forbidden)
    assert result == "CONNECTED"


async def test_offline_launcher_rechecks_stop_after_waiting_for_lock(db_session, monkeypatch):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.browser import profile_launcher

    monkeypatch.setattr(profile_launcher.sys, "platform", "darwin")
    binding = str(uuid4())
    mapping = {"profile_binding_id": binding, "profile_directory": "Profile 8", "automatic_launch_enabled": True,
        "chrome_profile_path": str(Path.home() / "Library/Application Support/Google/Chrome/Profile 8"),
        "verified_via": "owner_selected_chrome_version_page"}
    for key, value in [("chr_fixed_profile", mapping), ("chr_selection", {"profile_binding_id": binding}),
            ("naukri_automation", {"state": "RUNNING"})]:
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()
    actual_lock = profile_launcher.memory_row

    async def stopped_before_lock(session, **kwargs):
        state = await session.get(OwnerPreference, "naukri_automation")
        state.value = {"state": "STOPPED"}
        await actual_lock(session, **kwargs)

    async def forbidden(*_):
        pytest.fail("Stop won the lock; no launch probe or startup is allowed")

    monkeypatch.setattr(profile_launcher, "memory_row", stopped_before_lock)
    assert await profile_launcher.ensure_fixed_profile(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        settings=oauth_settings(CHROME_FIXED_PROFILE_LAUNCH_ENABLED=True), run=forbidden) == "PROFILE_OFFLINE"


async def test_fixed_profile_launcher_never_falls_back_or_claims_launch_as_connection(db_session, monkeypatch):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.browser.profile_launcher import ensure_fixed_profile
    test_session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr("backend.app.browser.profile_launcher.sys.platform", "darwin")
    binding = str(uuid4())
    mapping = {"profile_binding_id": binding, "profile_directory": "Default", "automatic_launch_enabled": True,
        "chrome_profile_path": str(Path.home() / "Library/Application Support/Google/Chrome/Default"),
        "verified_via": "owner_selected_chrome_version_page"}
    for key, value in [("chr_fixed_profile", mapping), ("chr_selection", {"profile_binding_id": binding}),
            ("naukri_automation", {"state": "RUNNING"})]:
        db_session.add(OwnerPreference(key=key, value=value))
    await db_session.commit()
    calls = []
    async def run(args):
        calls.append(args)
        return 1 if args[0].endswith("pgrep") else 0
    settings = oauth_settings(CHROME_FIXED_PROFILE_LAUNCH_ENABLED=True)
    assert await ensure_fixed_profile(test_session_factory, settings=settings, run=run) == "PROFILE_OFFLINE"
    assert calls[-1][-1] == "--profile-directory=Default"
    assert not any("user-data-dir" in arg or "debug" in arg for command in calls for arg in command)
    assert await ensure_fixed_profile(test_session_factory, settings=settings, run=run) == "PROFILE_OFFLINE"
    assert len(calls) == 2


async def test_pin_refuses_other_profile_and_paused_launcher_is_inert(db_session, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.agent.tools import ToolDenied
    from backend.app.browser.chrome_profiles import ProfileSelection, select_profile
    from backend.app.browser.profile_launcher import ensure_fixed_profile
    test_session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    db_session.add(OwnerPreference(key="chr_fixed_profile", value={"profile_binding_id": str(uuid4())}))
    await db_session.commit()
    with pytest.raises(ToolDenied, match="FIXED_PROFILE_REQUIRED"):
        await select_profile(db_session, ProfileSelection(expected_version=0, profile_binding_id=uuid4()))
    async def denied(args):
        pytest.fail("Stopped automation launched Chrome")
    monkeypatch.setattr("backend.app.browser.profile_launcher.sys.platform", "darwin")
    assert await ensure_fixed_profile(test_session_factory, settings=oauth_settings(CHROME_FIXED_PROFILE_LAUNCH_ENABLED=True), run=denied) == "PROFILE_OFFLINE"


@pytest.mark.parametrize("locked,expected", [(True, "LOCKED"), (False, "UNLOCKED")])
def test_current_macos_console_lock_requires_exact_active_user(locked, expected):
    from backend.scripts.monitor_naukri_acceptance import lock_observation
    document = {"IOConsoleLocked": locked, "IOConsoleUsers": [{"kCGSSessionUserIDKey": 501, "kCGSSessionOnConsoleKey": True}]}
    assert lock_observation(document, 501) == expected
    assert lock_observation(document, 502) == "UNKNOWN"
    document["IOConsoleUsers"][0]["kCGSSessionOnConsoleKey"] = False
    assert lock_observation(document, 501) == "UNKNOWN"


def test_conflicting_or_ambiguous_console_lock_is_unknown():
    from backend.scripts.monitor_naukri_acceptance import lock_observation
    document = {"IOConsoleLocked": True, "IOConsoleUsers": [{"kCGSSessionUserIDKey": 501, "kCGSSessionOnConsoleKey": True, "CGSSessionScreenIsLocked": False}]}
    assert lock_observation(document, 501) == "UNKNOWN"
