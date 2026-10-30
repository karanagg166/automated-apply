"""Real SQL persistence with fictional profiles/pages; no real accounts or HTTP."""

from uuid import UUID, uuid4

import pytest

from backend.app.browser import extension_tasks as tasks
from backend.app.browser.contracts import FillReceipt
from backend.app.browser.manual import dispatch_form
from backend.app.local_agent.contracts import Actor
from backend.app.local_agent.contracts import Command as NativeCommand
from backend.app.local_agent.service import dispatch
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.schemas.applications import AnswerEdit, QuestionInput, QuestionsAdd
from backend.app.services.applications.service import ApplicationPacketService
from backend.tests.chrome_profile_fixture import BINDING, SESSION, connected
from backend.tests.test_browser_forms import browser_target as browser_target_fixture
from backend.tests.test_browser_forms import config, inspection

browser_target = browser_target_fixture

EXTENSION = "a" * 32
ACTOR = Actor(channel="chrome", identity=EXTENSION)


def Command(**values):
    return NativeCommand(**{**BINDING, "browser_session_id": SESSION, **values})


def settings():
    return config(CHROME_EXTENSION_ID=EXTENSION)


async def opened(session, packet):
    session_id = SESSION
    await connected(session, settings(), session_id)
    result = await dispatch(session, settings(), ACTOR, Command(command="open_application_task",
        application_id=packet.id, browser_session_id=session_id, tab_id=17))
    assert result.ok, result.error_code
    return result.data["task"], session_id


def identity(task, session_id):
    return {"task_id": task["id"], "expected_task_version": task["version"],
            "browser_session_id": session_id, "tab_id": task["tab_id"]}


async def inspect_task(session, job, packet, task, session_id, fields=None, **changes):
    result = await dispatch_form(session, settings(), ACTOR, Command(command="inspect_form",
        application_id=packet.id, inspection=inspection(job.application_url, fields, **changes),
        **identity(task, session_id)))
    assert result.ok, result.error_code
    return result.data["task"], result.data["plan"]


@pytest.mark.asyncio
async def test_versioned_task_read_validates_window_and_current_packet(db_session, browser_target):
    _, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    context = identity(task, session_id)
    valid = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **context))
    assert valid.ok, valid.error_code
    wrong_window = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **context, window_id=11))
    assert wrong_window.error_code == "extension_tab_binding_mismatch"
    wrong_version = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **{**context, "expected_task_version": task["version"] + 1}))
    assert wrong_version.error_code == "extension_task_revision_conflict"
    # A packet edit after remote command start must fail the pre-inspection read.
    from backend.app.models.application_packet import ApplicationPacket
    row = await db_session.get(ApplicationPacket, packet.id)
    row.revision += 1
    await db_session.flush()
    stale = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **context))
    assert stale.error_code == "extension_task_context_stale"
    # Unversioned dashboard reads still expose the stale task for owner review.
    display = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", task_id=task["id"]))
    assert display.ok


async def test_dom_checkpoint_keeps_global_owner_lock_available(db_session, browser_target, monkeypatch):
    _, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    await db_session.commit()

    async def forbidden(*_, **__):
        pytest.fail("A read-only DOM checkpoint must not take the execution owner lock")

    monkeypatch.setattr("backend.app.execution.store.memory_row", forbidden)
    read = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **identity(task, session_id)))
    assert read.ok, read.error_code


async def test_posting_without_application_fields_saves_read_only_terminal(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    view = inspection(job.application_url, [])
    view.fields = []
    view.state = "manual_required"
    view.manual_reason = "verified_application_form_not_present"
    result = await dispatch_form(db_session, settings(), ACTOR, Command(command="inspect_form",
        application_id=packet.id, inspection=view, **identity(task, session_id)))
    assert result.ok, result.error_code
    assert result.data["task"]["state"] == "NEEDS_INPUT"
    assert result.data["plan"]["actions"] == [] and result.data["plan"]["state"] == "read_only"
    assert result.data["task"]["authorization_id"] is None


@pytest.mark.parametrize("pause_reason", [None, "owner_pause", "global_stop"])
async def test_explicit_open_refreshes_only_unbound_packet_and_preserves_stop(db_session, browser_target, pause_reason):
    from backend.app.models.application_packet import ApplicationPacket

    _, packet, _ = browser_target
    await connected(db_session, settings(), SESSION)
    first = await dispatch(db_session, settings(), ACTOR, Command(
        command="open_application_task", application_id=packet.id))
    assert first.ok
    task = first.data["task"]
    assert task["tab_id"] is None
    row = await tasks.load(db_session, task["id"])
    if pause_reason:
        tasks.move(db_session, row, "PAUSED", pause_reason)
    row.value = {**row.value, "plan_id": str(uuid4()), "authorization_id": str(uuid4())}
    saved = await db_session.get(ApplicationPacket, packet.id)
    saved.revision += 1
    await db_session.flush()
    opened_again = await dispatch(db_session, settings(), ACTOR, Command(
        command="open_application_task", application_id=packet.id))
    assert opened_again.ok, opened_again.error_code
    updated = opened_again.data["task"]
    assert updated["id"] == task["id"] and updated["packet_revision"] == saved.revision
    assert updated["plan_id"] is None and updated["authorization_id"] is None
    assert updated["tab_id"] is None and updated["counts"]["completed"] == 0
    assert updated["state"] == ("PAUSED" if pause_reason else "PACKET_READY")
    assert updated["reason"] == (pause_reason or "packet_changed_fresh_inspection_required")


@pytest.mark.parametrize("unsafe_state", ["bound", "guarded", "FILLING", "FILL_AUTHORIZED"])
async def test_open_cannot_refresh_a_bound_guarded_or_filling_task(db_session, browser_target, unsafe_state):
    from backend.app.models.application_packet import ApplicationPacket

    _, packet, _ = browser_target
    await connected(db_session, settings(), SESSION)
    first = await dispatch(db_session, settings(), ACTOR, Command(
        command="open_application_task", application_id=packet.id))
    row = await tasks.load(db_session, first.data["task"]["id"])
    change = {"tab_id": 17} if unsafe_state == "bound" else {"network_guard_active": True} if unsafe_state == "guarded" else {"state": unsafe_state}
    row.value = {**row.value, **change}
    saved = await db_session.get(ApplicationPacket, packet.id)
    saved.revision += 1
    await db_session.flush()
    result = await dispatch(db_session, settings(), ACTOR, Command(
        command="open_application_task", application_id=packet.id))
    assert not result.ok and result.error_code == "extension_task_context_stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["focus_lost", "active_tab_changed"])
async def test_focus_loss_allows_only_fresh_inspection_not_old_authorization(db_session, browser_target, event):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    changed = await dispatch(db_session, settings(), ACTOR, Command(
        command="update_application_task", task_event=event, **identity(task, session_id)))
    assert changed.ok
    paused = changed.data["task"]
    assert paused["state"] == "PAUSED" and paused["plan_id"] is None
    assert paused["authorization_id"] is None
    old = await dispatch_form(db_session, settings(), ACTOR, Command(
        command="authorize_form", plan_id=plan["id"], field_ids=["f0"], **identity(paused, session_id)))
    assert old.error_code == "extension_task_paused_or_cancelled"
    checked = await dispatch(db_session, settings(), ACTOR, Command(
        command="get_application_task", **identity(paused, session_id)))
    assert checked.ok, checked.error_code
    prepared, fresh_plan = await inspect_task(db_session, job, packet, paused, session_id)
    assert prepared["state"] in {"FORM_INSPECTED", "NEEDS_INPUT"}
    assert fresh_plan["id"] != plan["id"]
    assert prepared["authorization_id"] is None
    assert prepared["verified_receipts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["owner_pause", "global_stop", "refresh", "unexpected_navigation",
                                  "worker_restart_fresh_inspection_required", "browser_restart_fresh_inspection_required"])
async def test_focus_loss_never_replaces_a_stronger_pause_or_allows_inspection(db_session, browser_target, reason):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    row = await tasks.load(db_session, task["id"])
    paused = tasks.move(db_session, row, "PAUSED", reason, plan_id=None, authorization_id=None)
    changed = await dispatch(db_session, settings(), ACTOR, Command(
        command="update_application_task", task_event="focus_lost", **identity(paused, session_id)))
    assert changed.ok
    assert changed.data["task"]["reason"] == reason
    result = await dispatch_form(db_session, settings(), ACTOR, Command(
        command="inspect_form", application_id=packet.id, inspection=inspection(job.application_url),
        **identity(changed.data["task"], session_id)))
    assert result.error_code == "extension_task_paused_or_cancelled"


@pytest.mark.asyncio
async def test_binding_restart_pause_and_no_replay(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    assert task["counts"]["ready"] == 2
    command = Command(command="authorize_form", plan_id=plan["id"], field_ids=["f0", "f1"], **identity(task, session_id))
    authorized = await dispatch_form(db_session, settings(), ACTOR, command)
    assert authorized.ok, authorized.error_code
    assert authorized.data["task"]["state"] == "FILLING"
    replay = await dispatch_form(db_session, settings(), ACTOR, command)
    assert replay.error_code == "form_request_already_consumed"
    new_session = uuid4()
    heartbeat = await dispatch(db_session, settings(), ACTOR, Command(command="heartbeat_chrome_profile", browser_session_id=new_session))
    assert heartbeat.ok
    task = (await tasks.load(db_session, authorized.data["task"]["id"])).value
    recovered = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_id=task["id"], expected_task_version=task["version"], browser_session_id=new_session,
        task_event="recover"))
    assert recovered.ok
    assert recovered.data["task"]["state"] == "PAUSED"
    assert recovered.data["task"]["tab_id"] is None
    assert recovered.data["task"]["plan_id"] is None
    await db_session.commit()
    assert (await tasks.load(db_session, task["id"])).value["browser_session_id"] == str(new_session)


@pytest.mark.asyncio
@pytest.mark.parametrize("challenge", ["WIDGET_PRESENT_UNVERIFIED", "CHALLENGE_BLOCKING", "UNKNOWN"])
async def test_challenges_keep_proposals_read_only(db_session, browser_target, challenge):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id, challenge_state=challenge)
    assert plan["state"] == "read_only"
    assert task["state"] == "CHALLENGE_REQUIRED"
    denied = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert not denied.ok
    assert task["capabilities"]["unattended_approved"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("method,state", [("dom_assignment", "NEEDS_INPUT"), ("retained_after_blur", "READY_FOR_SUBMISSION")])
async def test_receipts_distinguish_assignment_retention_submission(db_session, browser_target, method, state):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id, [
        {"field_id": "f0", "kind": "email", "label": "Email", "required": True}])
    authorized = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert authorized.ok
    task = authorized.data["task"]
    received = await dispatch_form(db_session, settings(), ACTOR, Command(command="record_form_fill",
        receipt=FillReceipt(plan_id=plan["id"], verification_method=method, state="form_filled",
            results=[{"field_id": "f0", "status": "filled"}]), **identity(task, session_id)))
    assert received.ok, received.error_code
    assert received.data["task"]["state"] == state
    assert received.data["submitted"] is False
    assert received.data["task"]["counts"]["completed"] == (method == "retained_after_blur")


@pytest.mark.asyncio
async def test_dashboard_cancel_keeps_partial_receipt_and_original_authorization(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    authorization = Command(command="authorize_form", plan_id=plan["id"], field_ids=["f0", "f1"], **identity(task, session_id))
    result = await dispatch_form(db_session, settings(), ACTOR, authorization)
    task = result.data["task"]
    row = await tasks.load(db_session, task["id"])
    await tasks.control(db_session, settings(), row, "cancel", task["version"])
    result = await dispatch_form(db_session, settings(), ACTOR, Command(command="record_form_fill",
        receipt=FillReceipt(plan_id=plan["id"], state="manual_required", verification_method="retained_after_blur",
            results=[{"field_id": "f0", "status": "filled"}]), **identity(task, session_id)))
    assert result.ok, result.error_code
    assert result.data["task"]["state"] == "FAILED_FINAL"
    assert result.data["task"]["verified_receipts"][-1]["authorization_id"] == str(authorization.request_id)


@pytest.mark.asyncio
async def test_stale_packet_and_wrong_tab_cannot_authorize(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    wrong = {**identity(task, session_id), "tab_id": 99}
    denied = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **wrong))
    assert denied.error_code == "extension_tab_binding_mismatch"
    await ApplicationPacketService(db_session).add_questions(packet.id, QuestionsAdd(
        expected_revision=packet.revision, questions=[QuestionInput(question="First name")]))
    denied = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert not denied.ok


@pytest.mark.asyncio
async def test_name_parts_never_split_full_name_but_exact_reviewed_fact_fills(db_session, browser_target):
    job, packet, _ = browser_target
    fields = [{"field_id": "f0", "kind": "text", "label": "First name"},
              {"field_id": "f1", "kind": "text", "label": "Last name"}]
    from backend.app.browser.service import FormService
    plan = await FormService(db_session, settings()).inspect(packet.id, inspection(job.application_url, fields), "manual_extension")
    assert all(action.needs_input for action in plan.actions)
    service = ApplicationPacketService(db_session)
    packet = await service.add_questions(packet.id, QuestionsAdd(expected_revision=packet.revision,
        questions=[QuestionInput(question="First name")]))
    field = next(f for f in packet.fields if f.question == "First name")
    packet = await service.edit_answer(packet.id, field.id, AnswerEdit(expected_revision=packet.revision, answer="Alex"))
    row = await db_session.get(ApplicationPacketField, field.id)
    row.review_status = "reviewed"
    await db_session.flush()
    plan = await FormService(db_session, settings()).inspect(packet.id, inspection(job.application_url, fields), "manual_extension")
    assert plan.actions[0].value == "Alex"
    assert plan.actions[1].needs_input


@pytest.mark.asyncio
async def test_explicit_question_queue_correlates_owner_reply_and_keeps_step(db_session, browser_target):
    from types import SimpleNamespace

    from backend.app.dashboard.models import OwnerPreference
    from backend.app.execution import questions

    job, packet, _ = browser_target
    job.job_url = "https://www.naukri.com/job-listings-example-backend-123456789012"
    await db_session.flush()
    from backend.app.schemas.applications import PacketEdit
    packet = await ApplicationPacketService(db_session).edit(packet.id, PacketEdit(expected_revision=packet.revision, refresh_saved_data=True))
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id, [
        {"field_id": "f0", "kind": "date", "label": "Start date", "section": "Employment A",
         "page_step": "Experience", "semantic_key": "a" * 64, "required": True},
        {"field_id": "f1", "kind": "date", "label": "Start date", "section": "Employment B",
         "page_step": "Experience", "semantic_key": "b" * 64, "required": True},
    ])
    result = await dispatch(db_session, settings(), ACTOR, Command(command="ask_form_questions", **identity(task, session_id)))
    assert result.ok, result.error_code
    assert len(result.data["questions"]) == 2
    assert result.data["questions"][0]["id"] != result.data["questions"][1]["id"]
    q = result.data["questions"][0]
    stored = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    stored.value = {**stored.value, "state": "sent", "message_ids": [701]}
    owner = SimpleNamespace(TELEGRAM_OWNER_USER_ID=123, TELEGRAM_OWNER_CHAT_ID=456)
    message = {"from": {"id": 123}, "chat": {"id": 456, "type": "private"}, "text": "2020-01-02"}
    assert await questions.receive(db_session, owner, message, 1) is None
    invalid = {**message, "text": "tomorrow", "reply_to_message": {"message_id": 701}}
    assert "rejected" in await questions.receive(db_session, owner, invalid, 2)
    accepted = {**message, "reply_to_message": {"message_id": 701}}
    assert "saved" in await questions.receive(db_session, owner, accepted, 3)
    current = (await tasks.load(db_session, task["id"])).value
    assert current["step"] == "Experience" and current["tab_id"] == 17
    assert current["plan_id"] is None and current["state"] == "NEEDS_INPUT"
    assert "already answered" in await questions.receive(db_session, owner, accepted, 4)
    question_field = await db_session.get(ApplicationPacketField, UUID(q["field_id"]))
    assert question_field.human_answer == "2020-01-02"
    assert question_field.review_status == "pending"


@pytest.mark.asyncio
async def test_reload_widget_disappearance_does_not_clear_challenge(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, _ = await inspect_task(db_session, job, packet, task, session_id, challenge_state="WIDGET_PRESENT_UNVERIFIED")
    assert task["challenge_observed"]
    task, plan = await inspect_task(db_session, job, packet, task, session_id, challenge_state="NONE")
    assert plan["state"] == "read_only"
    assert plan["inspection"]["challenge_state"] == "UNKNOWN"
    assert task["state"] == "CHALLENGE_REQUIRED"


@pytest.mark.asyncio
async def test_manual_control_reasons_persist_and_dashboard_counts_them(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id, manual_controls=[{
        "control_id": "u0", "kind": "custom_combobox", "label": "Career stage",
        "reason": "Closed dropdown requires manual selection", "required": True,
    }])
    assert task["counts"]["manual"] == 1
    assert plan["inspection"]["manual_controls"][0]["label"] == "Career stage"
    assert all(action["field_id"] != "u0" for action in plan["actions"])


@pytest.mark.asyncio
async def test_task_poll_pauses_when_packet_changes_during_fill(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    authorization = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert authorization.ok
    await ApplicationPacketService(db_session).add_questions(packet.id, QuestionsAdd(
        expected_revision=packet.revision, questions=[QuestionInput(question="Confirmed first name")]))
    current = await dispatch(db_session, settings(), ACTOR, Command(command="get_application_task", task_id=task["id"]))
    assert current.ok
    assert current.data["task"]["state"] == "PAUSED"
    assert current.data["task"]["authorization_id"] is None
    assert current.data["task"]["reason"] == "candidate_or_packet_changed_during_fill"


@pytest.mark.asyncio
async def test_network_guard_state_preserves_plan_and_can_release_after_cancel(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    guarded = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="guard_installed", **identity(task, session_id)))
    assert guarded.ok
    task = guarded.data["task"]
    assert task["network_guard_active"] is True and task["plan_id"] == plan["id"]
    cancelled = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="cancel", **identity(task, session_id)))
    task = cancelled.data["task"]
    assert task["state"] == "FAILED_FINAL" and task["network_guard_active"]
    released = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="guard_released", **identity(task, session_id)))
    assert released.ok
    assert released.data["task"]["state"] == "FAILED_FINAL"
    assert released.data["task"]["network_guard_active"] is False


@pytest.mark.asyncio
async def test_global_stop_revokes_execution_but_preserves_partial_receipt(db_session, browser_target, async_client, phase2_auth):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    result = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0", "f1"], **identity(task, session_id)))
    assert result.ok
    task = result.data["task"]
    await db_session.commit()
    stopped = await async_client.post("/api/v1/browser/stop", headers=phase2_auth)
    assert stopped.status_code == 200
    assert (await tasks.load(db_session, task["id"])).value["state"] == "PAUSED"
    result = await dispatch_form(db_session, settings(), ACTOR, Command(command="record_form_fill",
        receipt=FillReceipt(plan_id=plan["id"], state="manual_required", verification_method="retained_after_blur",
            network_guard_active=True, results=[{"field_id": "f0", "status": "filled"}]), **identity(task, session_id)))
    assert result.ok, result.error_code
    assert result.data["task"]["state"] == "PAUSED"
    assert result.data["task"]["verified_receipts"][-1]["network_guard_active"] is True


@pytest.mark.asyncio
async def test_worker_restart_records_uncertain_fill_and_revokes_old_plan(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    result = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0", "f1"], **identity(task, session_id)))
    assert result.ok
    task = result.data["task"]
    recovered = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="worker_restart", **identity(task, session_id)))
    assert recovered.ok
    task = recovered.data["task"]
    assert task["state"] == "PAUSED" and task["plan_id"] is None
    assert task["counts"]["completed"] == 0
    assert task["verified_receipts"][-1]["verification_method"] == "unknown"
    assert task["verified_receipts"][-1]["plan_id"] == plan["id"]
    assert task["verified_receipts"][-1]["submitted"] is False


@pytest.mark.asyncio
async def test_truncated_question_cannot_generate_or_queue_an_inexact_answer(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    label = ("Email and complete application question " * 6)[:160]
    task, plan = await inspect_task(db_session, job, packet, task, session_id,
        [{"field_id": "f0", "kind": "text", "label": label}])
    assert plan["actions"][0]["needs_input"] is True
    assert plan["actions"][0]["value"] is None
    result = await tasks.ask_questions(db_session, settings(), await tasks.load(db_session, task["id"]))
    assert result["questions"] == []


@pytest.mark.asyncio
async def test_filled_native_field_with_unresolved_required_custom_combobox_never_ready_for_submission(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    # Plan has a native required field f0 and an unresolved required custom combobox u0
    task, plan = await inspect_task(db_session, job, packet, task, session_id,
        fields=[{"field_id": "f0", "kind": "email", "label": "Email", "required": True}],
        manual_controls=[{
            "control_id": "u0", "kind": "custom_combobox", "label": "Preferred Location",
            "reason": "Custom dropdown requires manual selection", "required": True,
        }])
    assert task["counts"]["manual"] == 1
    assert plan["inspection"]["manual_controls"][0]["required"] is True

    # Authorize native field
    authorized = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert authorized.ok
    task = authorized.data["task"]

    # Even with retained_after_blur and receipt reporting form_filled for native fields,
    # READY_FOR_SUBMISSION must NOT be reached while required manual controls remain unresolved
    received = await dispatch_form(db_session, settings(), ACTOR, Command(command="record_form_fill",
        receipt=FillReceipt(plan_id=plan["id"], verification_method="retained_after_blur", state="form_filled",
            results=[{"field_id": "f0", "status": "filled"}]), **identity(task, session_id)))
    assert received.ok, received.error_code
    # Must remain in a conservative manual-review status (FILLED_VERIFIED), NOT READY_FOR_SUBMISSION
    assert received.data["task"]["state"] != "READY_FOR_SUBMISSION"
    assert received.data["task"]["state"] == "FILLED_VERIFIED"
    assert received.data["task"]["counts"]["manual"] == 1
    assert received.data["submitted"] is False


@pytest.mark.asyncio
async def test_binding_replacement_tab_cannot_override_owner_pause_or_global_stop_until_resume(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    row = await tasks.load(db_session, task["id"])

    # 1. Explicit owner pause
    paused = await tasks.control(db_session, settings(), row, "pause", task["version"])
    assert paused["state"] == "PAUSED"
    assert paused["reason"] == "owner_pause"

    # 2. Tab is closed
    closed = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="tab_closed", **identity(paused, session_id)))
    assert closed.ok
    task = closed.data["task"]
    assert task["state"] == "PAUSED"
    assert task["tab_id"] is None
    assert task["reason"] == "owner_pause"

    # 3. Attempting to bind a replacement tab while paused must be denied
    denied = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="bind", **{**identity(task, session_id), "tab_id": 99}))
    assert not denied.ok
    assert denied.error_code == "extension_task_paused_or_cancelled"

    # Verify task state was not modified by the rejected bind attempt
    current = await tasks.load(db_session, task["id"])
    assert current.value["state"] == "PAUSED"
    assert current.value["tab_id"] is None
    assert current.value["reason"] == "owner_pause"

    # 4. Explicit authorized Resume lifts the pause
    resumed = await tasks.control(db_session, settings(), current, "resume", current.value["version"])
    assert resumed["reason"] == "owner_resume"

    # 5. Now replacement tab binding succeeds and moves to PACKET_READY
    bound = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="bind", **{**identity(resumed, session_id), "tab_id": 99}))
    assert bound.ok
    task = bound.data["task"]
    assert task["state"] == "PACKET_READY"
    assert task["tab_id"] == 99
    assert task["reason"] == "tab_bound_fresh_inspection_required"
    assert task["plan_id"] is None

    # Stale plan authorization or direct fill is rejected until fresh inspection
    denied_auth = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert not denied_auth.ok


@pytest.mark.asyncio
async def test_binding_replacement_tab_cannot_override_global_stop_until_resume(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    row = await tasks.load(db_session, task["id"])

    # Move to PAUSED via global_stop
    stopped = tasks.move(db_session, row, "PAUSED", "global_stop", plan_id=None, authorization_id=None)
    assert stopped["state"] == "PAUSED"
    assert stopped["reason"] == "global_stop"

    # Tab closed preserves global_stop
    closed = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="tab_closed", **identity(stopped, session_id)))
    assert closed.ok
    assert closed.data["task"]["reason"] == "global_stop"
    assert closed.data["task"]["tab_id"] is None

    # Bind is denied
    denied = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="bind", **{**identity(closed.data["task"], session_id), "tab_id": 88}))
    assert not denied.ok
    assert denied.error_code == "extension_task_paused_or_cancelled"


@pytest.mark.asyncio
async def test_owner_pause_race_with_in_flight_fill_preserves_pause_and_prevents_readiness(db_session, browser_target):
    job, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    task, plan = await inspect_task(db_session, job, packet, task, session_id)
    authorized = await dispatch_form(db_session, settings(), ACTOR, Command(command="authorize_form",
        plan_id=plan["id"], field_ids=["f0"], **identity(task, session_id)))
    assert authorized.ok
    task = authorized.data["task"]
    assert task["state"] == "FILLING"

    # Owner pauses while fill is in flight
    row = await tasks.load(db_session, task["id"])
    paused = await tasks.control(db_session, settings(), row, "pause", task["version"])
    assert paused["state"] == "PAUSED"
    assert paused["reason"] == "owner_pause"

    # Late fill receipt arrives from browser
    received = await dispatch_form(db_session, settings(), ACTOR, Command(command="record_form_fill",
        receipt=FillReceipt(plan_id=plan["id"], verification_method="retained_after_blur", state="form_filled",
            results=[{"field_id": "f0", "status": "filled"}]), **identity(paused, session_id)))
    assert received.ok
    # Receipt is recorded as audit evidence, but state REMAINS PAUSED!
    assert received.data["task"]["state"] == "PAUSED"
    assert received.data["task"]["reason"] == "owner_pause"

    # Tab closed keeps owner_pause
    closed = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="tab_closed", **identity(received.data["task"], session_id)))
    assert closed.ok
    assert closed.data["task"]["reason"] == "owner_pause"

    # Reopen / bind replacement tab is denied
    denied = await dispatch(db_session, settings(), ACTOR, Command(command="update_application_task",
        task_event="bind", **{**identity(closed.data["task"], session_id), "tab_id": 77}))
    assert not denied.ok
    assert denied.error_code == "extension_task_paused_or_cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["focus_lost", "active_tab_changed"])
async def test_duplicate_focus_observation_preserves_version_and_stale_commands_fail(db_session, browser_target, event):
    _, packet, _ = browser_target
    task, session_id = await opened(db_session, packet)
    first = await dispatch(db_session, settings(), ACTOR, Command(
        command="update_application_task", task_event=event, **identity(task, session_id)))
    paused = first.data["task"]
    again = await dispatch(db_session, settings(), ACTOR, Command(
        command="update_application_task", task_event=event, **identity(paused, session_id)))
    assert again.ok and again.data["task"] == paused
    stale = await dispatch(db_session, settings(), ACTOR, Command(
        command="update_application_task", task_event=event, **identity(task, session_id)))
    assert stale.error_code == "extension_task_revision_conflict"
