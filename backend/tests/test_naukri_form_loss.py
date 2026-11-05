"""Fictional lost-form reporting; no provider or real application writes."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_form_loss as loss
from backend.app.execution import naukri_questionnaires as forms
from backend.app.execution import questions
from backend.app.execution.queue_contracts import QueueControl
from backend.tests.test_naukri_questionnaires import entered, inspect, step
from backend.tests.test_naukri_submission import call
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def waiting(session, case):
    ctx, item = await entered(session, case)
    await inspect(session, case, ctx, item, step("Which office can you start from?", kind="choice", options=["Pune", "Delhi"]))
    assert await forms.prepare_one(async_sessionmaker(session.bind, expire_on_commit=False, autoflush=False), case.settings)
    row = await queue.load(session, item["id"])
    return ctx, item, row


@pytest.mark.parametrize("stopped", [False, True])
async def test_lost_form_quarantines_once_and_closes_unanswered_question_without_refund(db_session, upload_case, stopped):
    ctx, item, row = await waiting(db_session, upload_case)
    before = dict(row.value)
    question = await db_session.scalar(select(OwnerPreference).where(OwnerPreference.key.startswith(questions.PREFIX)))
    question.value = {**question.value, "state": "delivery_unknown"}
    row.value = {**row.value, "reconciliation_attempts": 3, "account_recheck_attempts": 3}
    if stopped:
        c = await queue.configuration(db_session)
        await queue.control(db_session, QueueControl(action="stop", expected_revision=c["revision"]))
    config = await queue.configuration(db_session)
    result = await call(db_session, upload_case, ctx, "poll_naukri_work", work_id=UUID(item["id"]), tab_id=before["form_binding"]["tab_id"], work_report={"kind": "needs_input", "reason": "original_questionnaire_tab_unavailable"})
    assert result.ok and result.data["form_loss_recorded"] and not result.data["submitted"]
    changed = (await queue.load(db_session, item["id"])).value
    assert changed["stage"] == "SUBMISSION_UNKNOWN" and changed["status"] == "unknown"
    assert changed["operation"] == "reconcile_application"
    assert changed["admitted_actions"] == before["admitted_actions"]
    assert changed["reconciliation_attempts"] == changed["account_recheck_attempts"] == 3
    assert question.value["state"] == "closed_form_unavailable" and not question.value.get("answer")
    assert await queue.configuration(db_session) == config
    revision = changed["revision"]
    assert not await loss.report(db_session, item["id"], before["form_binding"], upload_case.settings)
    assert (await queue.load(db_session, item["id"])).value["revision"] == revision


@pytest.mark.parametrize("field", ["tab_id", "window_id", "profile_binding_id", "browser_session_id", "admission", "account"])
async def test_loss_report_refuses_wrong_original_binding_and_preserves_work(db_session, upload_case, field):
    _, item, row = await waiting(db_session, upload_case)
    binding = dict(row.value["form_binding"])
    if field in {"tab_id", "window_id"}:
        binding[field] += 1
    elif field in {"profile_binding_id", "browser_session_id"}:
        binding[field] = str(uuid4())
    elif field == "admission":
        row.value = {**row.value, "admitted_actions": []}
    else:
        row.value = {**row.value, "account_sha256": "f" * 64}
    before = dict(row.value)
    with pytest.raises(ToolDenied):
        await loss.report(db_session, item["id"], binding, upload_case.settings)
    assert (await queue.load(db_session, item["id"])).value == before


@pytest.mark.parametrize("reconnect,mismatch", [(False, False), (True, False), (False, True)])
async def test_authenticated_new_session_fences_old_form_and_does_not_reopen_apply(db_session, upload_case, reconnect, mismatch):
    ctx, item, row = await waiting(db_session, upload_case)
    if mismatch:
        row.value = {**row.value, "account_sha256": "f" * 64}
    original = dict(row.value)
    changed = {**ctx, "browser_session_id": uuid4()}
    result = await call(db_session, upload_case, changed,
                        "connect_chrome_profile" if reconnect else "heartbeat_chrome_profile",
                        **({"profile_label": "Fictional profile"} if reconnect else {"profile_commands_enabled": True}))
    assert result.ok
    value = (await queue.load(db_session, item["id"])).value
    assert value["stage"] == "SUBMISSION_UNKNOWN" and value["status"] == "unknown"
    assert value["form_loss_observation"]["source"] == "authenticated_browser_session_replaced"
    assert value["admitted_actions"] == original["admitted_actions"]
    assert value["form_binding"] == original["form_binding"]


@pytest.mark.parametrize("window_id", [None, 99])
async def test_authenticated_window_loss_fences_the_original_form_and_versions_the_binding(db_session, upload_case, window_id):
    ctx, item, row = await waiting(db_session, upload_case)
    before = dict(row.value)
    result = await call(db_session, upload_case, {**ctx, "window_id": window_id}, "heartbeat_chrome_profile", profile_commands_enabled=True)
    assert result.ok
    value = (await queue.load(db_session, item["id"])).value
    assert value["stage"] == "SUBMISSION_UNKNOWN" and value["status"] == "unknown"
    assert value["form_loss_observation"]["source"] == "authenticated_browser_window_replaced"
    assert value["admitted_actions"] == before["admitted_actions"]
    assert value["form_binding"] == before["form_binding"]
