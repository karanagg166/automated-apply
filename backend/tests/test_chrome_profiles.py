"""Fictional owner profiles; never reads or changes installed Chrome accounts."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.browser import chrome_profiles as profiles
from backend.app.browser.chrome_telegram import command as telegram_command
from backend.app.browser.extension_tasks import load
from backend.app.browser.manual import dispatch_form
from backend.app.dashboard.models import OwnerPreference
from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.service import dispatch
from backend.tests.test_browser_forms import browser_target as browser_target_fixture
from backend.tests.test_browser_forms import config, inspection

browser_target = browser_target_fixture
EXTENSION = "a" * 32
ACTOR = Actor(channel="chrome", identity=EXTENSION)
OWNER = Actor(channel="owner", identity="primary")


def settings(**updates):
    return config(
        CHROME_EXTENSION_ID=EXTENSION,
        CHROME_PROFILE_COMMANDS_ENABLED=True,
        TELEGRAM_OWNER_USER_ID=11,
        TELEGRAM_OWNER_CHAT_ID=22,
        **updates,
    )


async def connect(session, label="Personal Chrome"):
    context = {
        "profile_binding_id": uuid4(),
        "profile_secret": uuid4().hex + uuid4().hex,
        "browser_session_id": uuid4(),
        "window_id": 10,
    }
    result = await dispatch(
        session,
        settings(),
        ACTOR,
        Command(command="connect_chrome_profile", profile_label=label, **context),
    )
    assert result.ok, result.error_code
    return context


async def choose(session, context):
    current = await profiles.selection(session)
    await profiles.select_profile(
        session,
        profiles.ProfileSelection(
            expected_version=current["version"],
            profile_binding_id=context["profile_binding_id"],
        ),
    )
    result = await dispatch(
        session,
        settings(),
        ACTOR,
        Command(
            command="heartbeat_chrome_profile", profile_commands_enabled=True, **context
        ),
    )
    assert result.ok, result.error_code
    await session.commit()
    return result.data["profile"]


async def queue(session, context, packet, **overrides):
    current = await profiles.selection(session)
    row = await session.get(
        OwnerPreference, profiles.PROFILE + str(context["profile_binding_id"])
    )
    data = profiles.ChromeCommandInput(
        **{
            "request_id": uuid4(),
            "profile_binding_id": context["profile_binding_id"],
            "selection_version": current["version"],
            "expected_profile_version": row.value["version"],
            "application_id": packet.id,
            "packet_revision": packet.revision,
            "action": "open",
            **overrides,
        }
    )
    return data, await profiles.enqueue(session, settings(), OWNER, data)


@pytest.mark.asyncio
async def test_two_profiles_only_selected_claims_and_controls_tasks(
    db_session, browser_target
):
    job, packet, _ = browser_target
    personal, jobs = (
        await connect(db_session),
        await connect(db_session, "Job applications"),
    )
    await choose(db_session, personal)
    data, queued = await queue(db_session, personal, packet)
    assert queued["state"] == "queued"
    denied = await dispatch(
        db_session, settings(), ACTOR, Command(command="poll_chrome_command", **jobs)
    )
    assert denied.error_code == "PROFILE_NOT_SELECTED"
    claimed = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="poll_chrome_command", **personal),
    )
    assert claimed.ok and claimed.data["command"]["id"] == queued["id"]
    again = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="poll_chrome_command", **personal),
    )
    assert again.data["command"] is None
    assert (await profiles.enqueue(db_session, settings(), OWNER, data))[
        "id"
    ] == queued["id"]
    opened = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **personal),
    )
    assert opened.ok
    task = opened.data["task"]
    assert task["profile_binding_id"] == str(personal["profile_binding_id"])
    await choose(db_session, jobs)
    assert (await load(db_session, task["id"])).value["state"] == "PAUSED"
    assert (await session_command(db_session, queued["id"]))[
        "state"
    ] == "outcome_unknown"
    old = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="get_application_task", task_id=task["id"], **personal),
    )
    assert old.error_code == "PROFILE_NOT_SELECTED"
    new = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **jobs),
    )
    assert new.ok
    assert new.data["task"]["profile_binding_id"] == str(jobs["profile_binding_id"])
    assert new.data["task"]["tab_id"] is None and new.data["task"]["plan_id"] is None


async def session_command(session, identity):
    await session.flush()
    return (
        await session.get(
            OwnerPreference, profiles.COMMAND + identity, populate_existing=True
        )
    ).value


@pytest.mark.asyncio
async def test_profile_credential_not_uuid_is_authentication(
    db_session, browser_target
):
    _, packet, _ = browser_target
    context = await connect(db_session)
    await choose(db_session, context)
    for changed in (
        {"profile_secret": "0" * 64},
        {"profile_binding_id": uuid4()},
        {"browser_session_id": uuid4()},
    ):
        denied = await dispatch(
            db_session,
            settings(),
            ACTOR,
            Command(
                command="open_application_task",
                application_id=packet.id,
                **{**context, **changed},
            ),
        )
        assert not denied.ok
    listing = await profiles.listing(db_session, settings())
    assert context["profile_secret"] not in str(listing)
    assert "secret_hash" not in str(listing)


@pytest.mark.asyncio
async def test_expiry_no_redelivery_stale_versions_and_channel_opt_in(
    db_session, browser_target
):
    _, packet, _ = browser_target
    context = await connect(db_session)
    await choose(db_session, context)
    data, queued = await queue(db_session, context, packet)
    with pytest.raises(ToolDenied, match="command_id_conflict"):
        await profiles.enqueue(
            db_session,
            settings(),
            OWNER,
            data.model_copy(update={"packet_revision": 99}),
        )
    row = await db_session.get(OwnerPreference, profiles.COMMAND + queued["id"])
    row.value = {
        **row.value,
        "expires_at": (profiles.now() - timedelta(seconds=1)).isoformat(),
    }
    result = await dispatch(
        db_session, settings(), ACTOR, Command(command="poll_chrome_command", **context)
    )
    assert result.data["command"] is None
    assert (await session_command(db_session, queued["id"]))["state"] == "expired"
    cfg = settings().model_copy(update={"CHROME_PROFILE_COMMANDS_ENABLED": False})
    with pytest.raises(ToolDenied, match="PROFILE_COMMANDS_DISABLED"):
        await profiles.enqueue(
            db_session, cfg, OWNER, data.model_copy(update={"request_id": uuid4()})
        )
    stale = data.model_copy(update={"request_id": uuid4(), "selection_version": 99})
    with pytest.raises(ToolDenied, match="PROFILE_SELECTION_CONFLICT"):
        await profiles.enqueue(db_session, settings(), OWNER, stale)


@pytest.mark.asyncio
async def test_native_start_and_ack_receipts_and_expired_leases(
    db_session, browser_target
):
    _, packet, _ = browser_target
    context = await connect(db_session)
    await choose(db_session, context)
    _, queued = await queue(db_session, context, packet)
    claimed = (
        await dispatch(
            db_session,
            settings(),
            ACTOR,
            Command(command="poll_chrome_command", **context),
        )
    ).data["command"]
    extra = {
        "chrome_command_id": queued["id"],
        "command_lease_token": claimed["lease_token"],
        "expected_command_version": claimed["version"],
    }
    started = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="start_chrome_command", **context, **extra),
    )
    assert started.ok
    stale = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="start_chrome_command", **context, **extra),
    )
    assert stale.error_code == "profile_command_revision_conflict"
    extra["expected_command_version"] = started.data["command"]["version"]
    ack = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="ack_chrome_command",
            command_outcome="completed",
            **context,
            **extra,
        ),
    )
    assert ack.ok and ack.data["command"]["state"] == "completed"
    assert ack.data["submitted"] is False
    _, next_command = await queue(db_session, context, packet)
    claimed = (
        await dispatch(
            db_session,
            settings(),
            ACTOR,
            Command(command="poll_chrome_command", **context),
        )
    ).data["command"]
    row = await db_session.get(OwnerPreference, profiles.COMMAND + next_command["id"])
    row.value = {
        **row.value,
        "lease_expires_at": (profiles.now() - timedelta(seconds=1)).isoformat(),
    }
    denied = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="start_chrome_command",
            chrome_command_id=claimed["id"],
            command_lease_token=claimed["lease_token"],
            expected_command_version=claimed["version"],
            **context,
        ),
    )
    assert not denied.ok
    assert (await session_command(db_session, next_command["id"]))[
        "state"
    ] == "outcome_unknown"


@pytest.mark.asyncio
async def test_browser_restart_offline_and_disconnect_revoke_forms(
    db_session, browser_target
):
    job, packet, _ = browser_target
    context = await connect(db_session)
    await choose(db_session, context)
    opened = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="open_application_task",
            application_id=packet.id,
            tab_id=17,
            **context,
        ),
    )
    task = opened.data["task"]
    identity = {
        "task_id": task["id"],
        "expected_task_version": task["version"],
        "tab_id": 17,
    }
    inspected = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="inspect_form",
            application_id=packet.id,
            inspection=inspection(job.application_url),
            **context,
            **identity,
        ),
    )
    assert inspected.ok
    restarted = {**context, "browser_session_id": uuid4()}
    heartbeat = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="heartbeat_chrome_profile", **restarted),
    )
    assert heartbeat.ok
    saved = (await load(db_session, task["id"])).value
    assert saved["state"] == "PAUSED" and saved["plan_id"] is None
    rejected = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="authorize_form",
            plan_id=inspected.data["plan"]["id"],
            field_ids=["f0"],
            **restarted,
            **{**identity, "expected_task_version": saved["version"]},
        ),
    )
    assert not rejected.ok
    row = await db_session.get(
        OwnerPreference, profiles.PROFILE + str(context["profile_binding_id"])
    )
    row.value = {
        **row.value,
        "last_heartbeat": (profiles.now() - timedelta(seconds=101)).isoformat(),
    }
    offline = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **restarted),
    )
    assert offline.error_code == "PROFILE_OFFLINE"
    row = await db_session.get(
        OwnerPreference, profiles.PROFILE + str(context["profile_binding_id"])
    )
    await profiles.disconnect(
        db_session, context["profile_binding_id"], row.value["version"]
    )
    denied = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="heartbeat_chrome_profile", **restarted),
    )
    assert denied.error_code == "PROFILE_OFFLINE"
    assert (await profiles.selection(db_session))["profile_binding_id"] is None


@pytest.mark.asyncio
async def test_telegram_routes_current_profile_no_duplicate_and_status_honest(
    db_session, browser_target
):
    _, packet, _ = browser_target
    context = await connect(db_session)
    await choose(db_session, context)
    text = f"/chrome open {packet.id} {packet.revision}"
    first = await telegram_command(db_session, settings(), text, 1, "fictional_bot")
    second = await telegram_command(db_session, settings(), text, 1, "fictional_bot")
    assert first == second and "queued" in first
    rows = list(
        (
            await db_session.scalars(
                select(OwnerPreference).where(
                    OwnerPreference.key.startswith(profiles.COMMAND)
                )
            )
        ).all()
    )
    assert len(rows) == 1 and rows[0].value["actor"] == "telegram"
    assert rows[0].value["profile_binding_id"] == str(context["profile_binding_id"])
    assert "queued" in await telegram_command(
        db_session, settings(), "/chrome status", 2, "fictional_bot"
    )
    assert "Filling requires" in await telegram_command(
        db_session, settings(), f"/chrome fill {packet.id} 1", 3, "fictional_bot"
    )
    assert "wrong bot" in await telegram_command(
        db_session,
        settings(),
        text.replace("/chrome", "/chrome@other"),
        4,
        "fictional_bot",
    )
    denied = Actor(channel="telegram", identity="999")
    with pytest.raises(ToolDenied, match="owner_identity_required"):
        await profiles.enqueue(
            db_session,
            settings(),
            denied,
            profiles.ChromeCommandInput(
                request_id=uuid4(),
                profile_binding_id=context["profile_binding_id"],
                selection_version=1,
                expected_profile_version=2,
                application_id=packet.id,
                packet_revision=1,
                action="open",
            ),
        )


@pytest.mark.asyncio
async def test_unbound_plan_cannot_be_authorized_in_another_profile_or_tab(
    db_session, browser_target
):
    job, packet, _ = browser_target
    personal, jobs = (
        await connect(db_session),
        await connect(db_session, "Job applications"),
    )
    await choose(db_session, personal)
    inspected = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="inspect_form",
            application_id=packet.id,
            inspection=inspection(job.application_url),
            tab_id=17,
            **personal,
        ),
    )
    assert inspected.ok
    plan = inspected.data["plan"]
    assert plan["profile_binding_id"] == str(personal["profile_binding_id"])
    await choose(db_session, jobs)
    denied = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="authorize_form",
            plan_id=plan["id"],
            field_ids=["f0"],
            tab_id=17,
            **jobs,
        ),
    )
    assert denied.error_code == "extension_tab_binding_mismatch"
    await choose(db_session, personal)
    wrong_tab = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="authorize_form",
            plan_id=plan["id"],
            field_ids=["f0"],
            tab_id=99,
            **personal,
        ),
    )
    assert wrong_tab.error_code == "extension_tab_binding_mismatch"
    old_plan = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="authorize_form",
            plan_id=plan["id"],
            field_ids=["f0"],
            tab_id=17,
            **personal,
        ),
    )
    assert not old_plan.ok


@pytest.mark.asyncio
async def test_default_queue_never_silently_uses_isolated_worker(
    db_session, browser_target
):
    from types import SimpleNamespace

    from backend.app.browser.queue import enqueue as browser_enqueue

    job, _, _ = browser_target
    campaign = SimpleNamespace(actor="owner:primary", id=uuid4())
    offline = await browser_enqueue(
        db_session, settings(), campaign, job, inspect_only=True
    )
    assert offline["status"] == "PROFILE_OFFLINE"
    personal = await connect(db_session)
    await choose(db_session, personal)
    opened = await browser_enqueue(
        db_session, settings(), campaign, job, inspect_only=True
    )
    assert opened["status"] == "pending_chrome"
    broad_fill = await browser_enqueue(db_session, settings(), campaign, job)
    assert broad_fill["status"] == "extension_field_approval_required"
    assert not list(
        (
            await db_session.scalars(
                select(OwnerPreference).where(
                    OwnerPreference.key.startswith("browser_job:")
                )
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_pause_survives_profile_switch_and_global_stop_cancels_commands(
    db_session, browser_target
):
    _, packet, _ = browser_target
    personal, jobs = (
        await connect(db_session),
        await connect(db_session, "Job applications"),
    )
    await choose(db_session, personal)
    opened = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **personal),
    )
    task = await load(db_session, opened.data["task"]["id"])
    from backend.app.browser.extension_tasks import control

    await control(db_session, settings(), task, "pause", task.value["version"])
    await choose(db_session, jobs)
    transferred = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **jobs),
    )
    assert transferred.ok and transferred.data["task"]["state"] == "PAUSED"
    assert transferred.data["task"]["reason"] == "owner_pause"
    _, queued = await queue(db_session, jobs, packet)
    await profiles.invalidate(
        db_session, str(jobs["profile_binding_id"]), "global_stop"
    )
    assert (await session_command(db_session, queued["id"]))["state"] == "cancelled"


@pytest.mark.asyncio
async def test_profile_routes_keep_owner_auth_and_extension_selection_boundary(
    async_client, phase2_auth
):
    assert (
        await async_client.get("/api/v1/browser/chrome-profiles")
    ).status_code == 401
    value = await async_client.get(
        "/api/v1/browser/chrome-profiles", headers=phase2_auth
    )
    assert (
        value.status_code == 200
        and value.json()["selection"]["profile_binding_id"] is None
    )
    denied = await async_client.post(
        "/api/v1/browser/chrome-profiles/select",
        headers={**phase2_auth, "X-Agent-Client": EXTENSION},
        json={"expected_version": 0, "profile_binding_id": str(uuid4())},
    )
    assert denied.status_code == 403


def test_native_profile_credential_is_unwrapped_only_on_authenticated_transport():
    import httpx

    from backend.app.local_agent.native_host import forward

    context = {
        "profile_binding_id": uuid4(),
        "profile_secret": "f" * 64,
        "browser_session_id": uuid4(),
        "window_id": 10,
    }
    request = Command(command="heartbeat_chrome_profile", **context)
    assert "f" * 64 not in request.model_dump_json() and "f" * 64 not in repr(request)

    def handle(message):
        import json

        value = json.loads(message.content)
        assert value["profile_secret"] == "f" * 64
        assert (
            message.headers["authorization"]
            == "Bearer fictional-only-native-test-token"
        )
        assert message.headers["x-agent-client"] == EXTENSION
        return httpx.Response(
            200,
            json={
                "version": 1,
                "request_id": str(request.request_id),
                "ok": True,
                "capability": "chrome_profile",
                "data": {"submitted": False},
            },
        )

    result = forward(
        request,
        settings(
            CHROME_NATIVE_MESSAGING_ENABLED=True,
            JOB_AGENT_API_TOKEN="fictional-only-native-test-token",
        ),
        httpx.Client(transport=httpx.MockTransport(handle)),
    )
    assert result["ok"]


@pytest.mark.asyncio
async def test_late_partial_receipt_survives_transfer_without_changing_new_task(
    db_session, browser_target
):
    from backend.app.browser.contracts import FillReceipt
    from backend.app.browser.service import FormService

    job, packet, _ = browser_target
    personal, jobs = (
        await connect(db_session),
        await connect(db_session, "Job applications"),
    )
    await choose(db_session, personal)
    opened = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="open_application_task",
            application_id=packet.id,
            tab_id=17,
            **personal,
        ),
    )
    task = opened.data["task"]
    identity = {
        "task_id": task["id"],
        "expected_task_version": task["version"],
        "tab_id": 17,
    }
    inspected = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="inspect_form",
            application_id=packet.id,
            inspection=inspection(job.application_url),
            **personal,
            **identity,
        ),
    )
    identity["expected_task_version"] = inspected.data["task"]["version"]
    plan_id = inspected.data["plan"]["id"]
    authorized = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="authorize_form",
            plan_id=plan_id,
            field_ids=["f0"],
            **personal,
            **identity,
        ),
    )
    assert authorized.ok
    await choose(db_session, jobs)
    transferred = await dispatch(
        db_session,
        settings(),
        ACTOR,
        Command(command="open_application_task", application_id=packet.id, **jobs),
    )
    version = transferred.data["task"]["version"]
    result = await dispatch_form(
        db_session,
        settings(),
        ACTOR,
        Command(
            command="record_form_fill",
            receipt=FillReceipt(
                plan_id=plan_id,
                verification_method="retained_after_blur",
                state="manual_required",
                results=[{"field_id": "f0", "status": "filled"}],
            ),
            **personal,
            **identity,
        ),
    )
    assert result.ok and result.data["historical_profile_receipt"] is True
    assert (await load(db_session, task["id"])).value["version"] == version
    _, plan = await FormService(db_session, settings()).load(UUID(plan_id))
    assert plan.state == "finished"
    listing = await profiles.listing(db_session, settings())
    receipt = listing["receipts"][-1]
    assert receipt["profile_binding_id"] == str(personal["profile_binding_id"])
    assert receipt["verification_method"] == "retained_after_blur"
    assert receipt["results"] == [
        {"field_id": "f0", "status": "filled"}
    ]
    status = await telegram_command(
        db_session, settings(), "/chrome status", 99, "fictional_bot"
    )
    assert (
        str(personal["profile_binding_id"]) in status and "1 retained fields" in status
    )
