"""Fictional original-tab recovery; never a provider request or action."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.browser import chrome_profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_questionnaires as forms
from backend.app.execution.naukri_unanswered_recovery import recover
from backend.app.execution.queue_contracts import QueueControl
from backend.tests.test_naukri_questionnaires import entered, inspect, step
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


@pytest.mark.parametrize("change", [None, "answered", "steps", "tab", "expired", "nonempty", "question", "account", "revision"])
async def test_only_untouched_first_question_can_recover_without_new_apply(db_session, upload_case, change):
    case = upload_case
    ctx, item = await entered(db_session, case)
    await inspect(db_session, case, ctx, item, step("Any Java training attended?"))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    assert await forms.prepare_one(factory, case.settings)
    value = dict((await queue.load(db_session, item["id"])).value)
    assert value["reason"] == "questionnaire_verified_answer_required"
    config = await queue.configuration(db_session)
    await queue.control(db_session, QueueControl(action="stop", expected_revision=config["revision"]))
    row = await queue.load(db_session, item["id"])
    value = dict(row.value)
    original = dict(value["form_binding"])
    p = await db_session.get(OwnerPreference, chrome_profiles.PROFILE + original["profile_binding_id"])
    p.value = {**p.value, "browser_session_id": str(uuid4())}
    binding = {"profile_binding_id": p.value["id"], "browser_session_id": p.value["browser_session_id"], "window_id": p.value["window_id"], "tab_id": original["tab_id"]}
    proof = {"binding": binding, "work_id": value["id"], "url": value["url"], "requisition": value["requisition"], "observed_at": datetime.now(timezone.utc).isoformat(), "empty_first_question": True, "questionnaire": {"kind": "questionnaire", **step("Any Java training attended?")}}
    if change == "answered": value["admitted_actions"] = [*value["admitted_actions"], {"fingerprint": "answer_questionnaire:old", "id": str(uuid4())}]
    if change == "steps": value["questionnaire_steps"] = 1
    if change == "tab": proof["binding"]["tab_id"] += 1
    if change == "expired": proof["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    if change == "nonempty": proof["empty_first_question"] = False
    if change == "question": proof["questionnaire"] = {"kind": "questionnaire", **step("Changed question?")}
    if change == "account": value["account_sha256"] = "f" * 64
    row.value = value
    revision = value["revision"] - (1 if change == "revision" else 0)
    admissions = list(value["admitted_actions"])
    if change:
        with pytest.raises(ToolDenied):
            await recover(db_session, item["id"], revision, proof)
        assert (await queue.load(db_session, item["id"])).value["admitted_actions"] == admissions
    else:
        recovered = await recover(db_session, item["id"], revision, proof)
        assert recovered["admitted_actions"] == admissions and len(admissions) == 1
        assert recovered["stage"] == "PAUSED" and recovered["questionnaire_document_id"] == proof["questionnaire"]["document_id"]
        assert recovered["form_binding"]["tab_id"] == original["tab_id"]
        assert recovered["form_binding"]["browser_session_id"] != original["browser_session_id"]
        assert recovered["unanswered_session_recoveries"][0]["old_form_binding"] == original
        assert (await queue.configuration(db_session))["state"] == "STOPPED"


@pytest.mark.parametrize("change", [None, "apply_document", "browser_session", "selected", "kind", "fingerprint", "answer", "packet", "reason"])
async def test_unparsed_radio_requires_exact_untouched_apply_document_and_never_repeats_apply(db_session, upload_case, change):
    from uuid import UUID

    from backend.app.models.application_packet import ApplicationPacket

    _, item = await entered(db_session, upload_case)
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "stage": "SUBMISSION_UNKNOWN", "status": "queued", "operation": "reconcile_application",
                 "reason": "exact_application_history_row_required"}
    config = await queue.configuration(db_session)
    await queue.control(db_session, QueueControl(action="stop", expected_revision=config["revision"]))
    row = await queue.load(db_session, item["id"])
    value = dict(row.value)
    original = value["form_binding"]
    proof = {"binding": {k: original[k] for k in ("profile_binding_id", "browser_session_id", "window_id", "tab_id")},
             "work_id": value["id"], "url": value["url"], "requisition": value["requisition"],
             "observed_at": datetime.now(timezone.utc).isoformat(), "empty_first_question": True,
             "apply_document_id": value["document_id"], "control_kind": "naukri_single_select_radio",
             "questionnaire": {"kind": "questionnaire", **step("Are you willing to attend in-person interview?", kind="choice", options=["Yes", "No"])}}
    if change == "apply_document": proof["apply_document_id"] = str(uuid4())
    if change == "browser_session": proof["binding"]["browser_session_id"] = str(uuid4())
    if change == "selected": proof["empty_first_question"] = False
    if change == "kind": proof["control_kind"] = "unknown"
    if change == "fingerprint": proof["questionnaire"]["step_sha256"] = "f" * 64
    if change == "answer": value["admitted_actions"] = [*value["admitted_actions"], {"fingerprint": "answer_questionnaire:old"}]
    if change == "reason": value["paused_context"] = {**value["paused_context"], "reason": "unknown_final_submission"}
    if change == "packet":
        packet = await db_session.get(ApplicationPacket, UUID(value["packet_id"]))
        packet.lifecycle_state = "submission_unknown"
    row.value = value
    admissions = list(value["admitted_actions"])
    if change:
        with pytest.raises(ToolDenied):
            await recover(db_session, item["id"], value["revision"], proof)
    else:
        recovered = await recover(db_session, item["id"], value["revision"], proof)
        assert recovered["stage"] == "PAUSED" and recovered["questionnaire"]["options"] == ["Yes", "No"]
        assert recovered["paused_context"] == {"stage": "QUESTIONS", "status": "queued", "operation": "prepare_questionnaire", "reason": None}
        assert recovered["form_binding"]["tab_id"] == original["tab_id"]
        assert (await queue.configuration(db_session))["state"] == "STOPPED"
        with pytest.raises(ToolDenied):
            await recover(db_session, item["id"], recovered["revision"], proof)
        config = await queue.configuration(db_session)
        await queue.control(db_session, QueueControl(action="start", expected_revision=config["revision"]))
        refreshed = (await queue.load(db_session, item["id"])).value
        assert refreshed["stage"] == "QUESTIONS" and refreshed["status"] == "queued"
        assert refreshed["operation"] == "refresh_questionnaire_profile"
        assert not refreshed.get("questionnaire_answer")
    assert (await queue.load(db_session, item["id"])).value["admitted_actions"] == admissions


async def test_interview_willingness_requires_owner_fact_even_with_submission_authorization(db_session, upload_case):
    ctx, item = await entered(db_session, upload_case)
    await inspect(db_session, upload_case, ctx, item,
                  step("Are you willing to attend in-person interview?", kind="choice", options=["Yes", "No"]))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    assert await forms.prepare_one(factory, upload_case.settings)
    waiting = (await queue.load(db_session, item["id"])).value
    assert waiting["stage"] == "NEEDS_INPUT" and waiting["reason"] == "questionnaire_verified_answer_required"
    assert not waiting.get("questionnaire_answer")
    assert len(waiting["admitted_actions"]) == 1
