"""Real SQL persistence with fictional profiles/pages; no real accounts or HTTP."""

from uuid import UUID, uuid4

import pytest

from backend.app.browser import extension_tasks as tasks
from backend.app.browser.contracts import FillReceipt
from backend.app.browser.manual import dispatch_form
from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.service import dispatch
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.schemas.applications import AnswerEdit, QuestionInput, QuestionsAdd
from backend.app.services.applications.service import ApplicationPacketService
from backend.tests.test_browser_forms import browser_target as browser_target_fixture
from backend.tests.test_browser_forms import config, inspection

browser_target = browser_target_fixture

EXTENSION = "a" * 32
ACTOR = Actor(channel="chrome", identity=EXTENSION)


def settings():
    return config(CHROME_EXTENSION_ID=EXTENSION)


async def opened(session, packet):
    session_id = uuid4()
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
    task = authorized.data["task"]
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
