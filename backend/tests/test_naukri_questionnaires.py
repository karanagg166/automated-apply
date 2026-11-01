"""Isolated continuation/Telegram/packet fences; no provider or real application."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_questionnaires as forms
from backend.app.execution.queue_contracts import QueueControl
from backend.app.models.application_packet import ApplicationPacket
from backend.tests.test_naukri_submission import (
    admit,
    apply_ready,
    call,
    claim,
    finish,
    history_ready,
    observation,
)
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


def step(
    question="What is your full name?", *, options=None, document_id=None, kind="text"
):
    from backend.tests.test_application_queue import URL

    options = options or []
    signature = hashlib.sha256(
        json.dumps([URL, question, kind, options], separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "document_id": document_id or str(uuid4()),
        "step_sha256": signature,
        "question": question,
        "answer_kind": kind,
        "options": options,
        "max_characters": 4000,
    }


async def entered(session, case):
    ctx, item, work = await apply_ready(session, case)
    work = await admit(session, case, ctx, work)
    report = observation(
        work, "QUESTIONNAIRE", document_id=work["execution"]["document_id"]
    )
    await finish(session, case, ctx, work, report)
    value = (await queue.load(session, item["id"])).value
    assert value["form_pending"] and value["stage"] == "QUESTIONS"
    assert len(value["admitted_actions"]) == 1
    return ctx, item


async def inspect(session, case, ctx, item, question):
    work = await admit(session, case, ctx, await claim(session, case, ctx))
    assert work["operation"] == "inspect_questionnaire"
    await finish(
        session,
        case,
        ctx,
        work,
        {
            "kind": "questionnaire",
            "observed_url": work["url"],
            "requisition": work["requisition"],
            "questionnaire": question,
        },
    )


async def test_questionnaire_retains_terminal_packet_fence_and_builds_a_grounded_answer(
    db_session, upload_case
):
    case = upload_case
    ctx, item = await entered(db_session, case)
    await inspect(db_session, case, ctx, item, step())
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    assert await forms.prepare_one(factory, case.settings)
    v = (await queue.load(db_session, item["id"])).value
    assert v["operation"] == "refresh_questionnaire_profile" and v["status"] == "queued"
    assert v["questionnaire_answer"]["answer"]
    assert v["questionnaire_answer"]["evidence"]
    p = await db_session.get(
        ApplicationPacket, UUID(v["packet_id"]), populate_existing=True
    )
    assert p.lifecycle_state == "submitting" and len(v["admitted_actions"]) == 1


async def test_unknown_personal_answer_uses_existing_owner_question_channel_and_refreshes_before_resume(
    db_session, upload_case
):
    case = upload_case
    ctx, item = await entered(db_session, case)
    await inspect(
        db_session,
        case,
        ctx,
        item,
        step(
            "Which office can you start from?", kind="choice", options=["Pune", "Delhi"]
        ),
    )
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    assert await forms.prepare_one(factory, case.settings)
    from sqlalchemy import select

    from backend.app.execution import questions

    q = await db_session.scalar(
        select(OwnerPreference).where(OwnerPreference.key.startswith(questions.PREFIX))
    )
    assert q.value["queue_work_id"] == item["id"] and not q.value["reuse_approved"]
    assert await forms.question_current(db_session, q.value)
    await db_session.commit()
    settings = case.settings.model_copy(
        update={"TELEGRAM_OWNER_USER_ID": 123, "TELEGRAM_OWNER_CHAT_ID": 456}
    )

    class Bot:
        calls = 0

        async def call(self, method, payload):
            assert (
                method == "sendMessage"
                and payload["chat_id"] == 456
                and "Which office" in payload["text"]
            )
            self.calls += 1
            return {"message_id": 991}

    bot = Bot()
    assert await questions.deliver_one(factory, settings, bot)
    assert not await questions.deliver_one(factory, settings, bot)
    message = {
        "from": {"id": 123},
        "chat": {"id": 456, "type": "private"},
        "reply_to_message": {"message_id": 991},
        "text": "Pune",
    }
    from backend.app.agent.tools import ToolDenied

    with pytest.raises(ToolDenied, match="telegram_owner_required"):
        await questions.receive(
            db_session, settings, {**message, "from": {"id": 999}}, 1
        )
    assert (
        await questions.receive(
            db_session,
            settings,
            {**message, "reply_to_message": {"message_id": 990}},
            2,
        )
        is None
    )
    answer = await questions.receive(db_session, settings, message, 3)
    assert "No second Apply" in answer
    await db_session.commit()
    v = (await queue.load(db_session, item["id"])).value
    assert (
        v["operation"] == "refresh_questionnaire_profile"
        and v["questionnaire_answer"]["answer"] == "Pune"
    )
    assert len(v["admitted_actions"]) == 1
    assert "already answered" in await questions.receive(
        db_session, settings, message, 3
    )
    assert bot.calls == 1
    assert not await forms.question_current(db_session, q.value)


@pytest.mark.parametrize("reason", ["browser_worker_restarted", "owner_tab_active"])
async def test_lost_form_read_reconciles_only_without_second_apply(
    db_session, upload_case, reason
):
    case = upload_case
    ctx, item = await entered(db_session, case)
    work = await admit(db_session, case, ctx, await claim(db_session, case, ctx))
    result = await call(
        db_session,
        case,
        ctx,
        "abandon_naukri_work",
        work,
        work_report={"kind": "failed", "reason": reason},
    )
    assert result.ok
    v = (await queue.load(db_session, item["id"])).value
    assert v["status"] == "unknown" and v["stage"] == "SUBMISSION_UNKNOWN"
    assert len(v["admitted_actions"]) == 1


async def test_stop_invalidates_original_questionnaire_lease(db_session, upload_case):
    case = upload_case
    ctx, item = await entered(db_session, case)
    work = await admit(db_session, case, ctx, await claim(db_session, case, ctx))
    config = await queue.configuration(db_session)
    await queue.control(
        db_session, QueueControl(action="stop", expected_revision=config["revision"])
    )
    result = await call(
        db_session,
        case,
        ctx,
        "finish_naukri_work",
        work,
        work_report={
            "kind": "questionnaire",
            "observed_url": work["url"],
            "requisition": work["requisition"],
            "questionnaire": step(),
        },
    )
    assert not result.ok and result.error_code == "queue_lease_lost"
    assert (
        len((await queue.load(db_session, item["id"])).value["admitted_actions"]) == 1
    )


async def test_questionnaire_step_hash_cannot_be_rebound_to_a_different_question(
    db_session, upload_case
):
    case = upload_case
    ctx, item = await entered(db_session, case)
    work = await admit(db_session, case, ctx, await claim(db_session, case, ctx))
    wrong = {**step(), "question": "Another question"}
    r = await call(
        db_session,
        case,
        ctx,
        "finish_naukri_work",
        work,
        work_report={
            "kind": "questionnaire",
            "observed_url": work["url"],
            "requisition": work["requisition"],
            "questionnaire": wrong,
        },
    )
    assert not r.ok and r.error_code == "questionnaire_step_evidence_changed"


async def answered_ready(session, case):
    from backend.tests.test_naukri_background_queue import job_report

    ctx, item = await entered(session, case)
    question = step()
    await inspect(session, case, ctx, item, question)
    factory = async_sessionmaker(session.bind, expire_on_commit=False, autoflush=False)
    assert await forms.prepare_one(factory, case.settings)
    work = await admit(session, case, ctx, await claim(session, case, ctx))
    assert work["operation"] == "refresh_questionnaire_profile"
    work = await finish(
        session,
        case,
        ctx,
        work,
        observation(
            work,
            "PROFILE_VERIFIED",
            resume_sha256=case.private.sha256,
            resume_bytes=len(case.raw),
        ),
    )
    assert work["operation"] == "refresh_questionnaire_job"
    work = await admit(session, case, ctx, work)
    work = await finish(session, case, ctx, work, job_report())
    assert work["operation"] == "inspect_questionnaire"
    work = await admit(session, case, ctx, work)
    work = await finish(
        session,
        case,
        ctx,
        work,
        {
            "kind": "questionnaire",
            "observed_url": work["url"],
            "requisition": work["requisition"],
            "questionnaire": question,
        },
    )
    assert work["operation"] == "answer_questionnaire"
    return ctx, item, work, question


async def test_refresh_fill_and_independent_history_receipts_never_repeat_apply(
    db_session, upload_case
):
    from backend.app.execution.naukri_receipts import prevents_replay

    case = upload_case
    ctx, item, work, question = await answered_ready(db_session, case)
    work = await admit(db_session, case, ctx, work)
    assert work["execution"]["questionnaire"]["answer"]
    await finish(
        db_session,
        case,
        ctx,
        work,
        {
            "kind": "questionnaire_answer_attempted",
            "observed_url": work["url"],
            "requisition": work["requisition"],
            "document_id": question["document_id"],
            "step_sha256": question["step_sha256"],
        },
    )
    v = (await queue.load(db_session, item["id"])).value
    assert len(v["admitted_actions"]) == 2
    assert (
        len(v["questionnaire_answers"]) == 1
        and v["questionnaire_answers"][0]["answer"]["answer"]
    )
    assert (
        sum(a["fingerprint"].startswith("apply:") for a in v["admitted_actions"]) == 1
    )
    # The widget disappears after a successful answer; that is not a receipt.
    check = await admit(db_session, case, ctx, await claim(db_session, case, ctx))
    await finish(
        db_session,
        case,
        ctx,
        check,
        {"kind": "needs_input", "reason": "questionnaire_drawer_unrecognized"},
    )
    assert not await prevents_replay(db_session, item["requisition"])
    assert (
        await claim(db_session, case, ctx) is None
    )  # Bounded read-only reconciliation cooldown.
    row = await queue.load(db_session, item["id"])
    row.value = {
        **row.value,
        "available_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.commit()
    for _ in range(2):
        check = await history_ready(db_session, case, ctx)
        await finish(
            db_session,
            case,
            ctx,
            check,
            observation(
                check,
                "APPLICATION_SENT",
                title="Backend Developer",
                company="Fictional Labs",
            ),
        )
    v = (await queue.load(db_session, item["id"])).value
    assert v["stage"] == "SUBMITTED_CONFIRMED" and not v["form_pending"]
    assert len(v["admitted_actions"]) == 2 and await prevents_replay(
        db_session, item["requisition"]
    )


async def test_lost_answer_response_is_unknown_and_a_second_answer_admission_is_rejected(
    db_session, upload_case
):
    case = upload_case
    ctx, item, work, _ = await answered_ready(db_session, case)
    work = await admit(db_session, case, ctx, work)
    await finish(
        db_session,
        case,
        ctx,
        work,
        {"kind": "failed", "reason": "native_response_lost"},
    )
    row = await queue.load(db_session, item["id"])
    assert row.value["status"] == "unknown" and len(row.value["admitted_actions"]) == 2
    # Even a damaged caller trying to requeue this exact consumed step is fenced.
    row.value = {**row.value, "status": "queued", "operation": "answer_questionnaire"}
    await db_session.commit()
    retry = await claim(db_session, case, ctx)
    r = await call(db_session, case, ctx, "admit_naukri_work", retry)
    assert not r.ok and r.error_code == "queue_action_replay_forbidden"
    assert (
        len((await queue.load(db_session, item["id"])).value["admitted_actions"]) == 2
    )


async def test_expired_account_proof_cannot_authorize_a_questionnaire_write(
    db_session, upload_case
):
    case = upload_case
    ctx, item, work, _ = await answered_ready(db_session, case)
    row = await queue.load(db_session, item["id"])
    row.value = {
        **row.value,
        "account_observation": {
            **row.value["account_observation"],
            "observed_at": (
                datetime.now(timezone.utc) - timedelta(minutes=3)
            ).isoformat(),
        },
    }
    await db_session.commit()
    r = await call(db_session, case, ctx, "admit_naukri_work", work)
    assert (
        not r.ok and r.error_code == "questionnaire_fresh_profile_observation_required"
    )
    assert (
        len((await queue.load(db_session, item["id"])).value["admitted_actions"]) == 1
    )


async def test_reuse_is_explicit_and_scoped_to_question_profile_and_job_facts(
    db_session, upload_case
):
    from sqlalchemy import select

    from backend.app.execution import questions

    case = upload_case
    ctx, item = await entered(db_session, case)
    question = step(
        "Which office can you start from?", kind="choice", options=["Pune", "Delhi"]
    )
    await inspect(db_session, case, ctx, item, question)
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    assert await forms.prepare_one(factory, case.settings)
    q = await db_session.scalar(
        select(OwnerPreference).where(OwnerPreference.key.startswith(questions.PREFIX))
    )
    now = datetime.now(timezone.utc)
    await forms.answer_question(db_session, q, "Pune", now, case.settings)
    assert await db_session.get(OwnerPreference, q.value["reuse_key"]) is None
    await forms.approve_reuse(db_session, q)
    await db_session.commit()
    value = dict((await queue.load(db_session, item["id"])).value)
    assert await db_session.get(OwnerPreference, q.value["reuse_key"])
    # Reuse is a separate opt-in; the original immutable packet is untouched.
    value.pop("questionnaire_answer")
    value.update(
        operation="prepare_questionnaire",
        status="queued",
        lease_token=None,
        lease_until=None,
    )
    row = await queue.load(db_session, item["id"])
    row.value = value
    await db_session.commit()
    assert await forms.prepare_one(factory, case.settings)
    value = (await queue.load(db_session, item["id"])).value
    assert value["questionnaire_answer"]["source"] == "owner_approved_reuse"
    assert value["questionnaire_answer"]["answer"] == "Pune"
    assert forms.reuse_key(value, question) != forms.reuse_key(
        {**value, "profile_version": value["profile_version"] + 1}, question
    )
    narrative = step("Why do you want to join this company?")
    assert forms.reuse_key(value, narrative) != forms.reuse_key(
        {
            **value,
            "facts": {**value["facts"], "description": "Changed genuine requirements"},
        },
        narrative,
    )
    q.value = {**q.value, "reuse_approved": False}
    await db_session.commit()
    from backend.app.agent.tools import ToolDenied

    with pytest.raises(ToolDenied, match="questionnaire_owner_answer_changed"):
        await forms.context(db_session, value, case.settings, writing=True)


async def test_extra_resume_upload_is_held_without_asking_for_a_text_answer(
    db_session, upload_case
):
    from sqlalchemy import select

    from backend.app.execution import questions

    case = upload_case
    ctx, item = await entered(db_session, case)
    await inspect(
        db_session,
        case,
        ctx,
        item,
        step(
            "Please upload your resume", kind="file", options=["Upload Resume", "Later"]
        ),
    )
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    assert await forms.prepare_one(factory, case.settings)
    value = (await queue.load(db_session, item["id"])).value
    assert value["reason"] == "questionnaire_supported_resume_attachment_required"
    assert not value.get("questionnaire_answer") and len(value["admitted_actions"]) == 1
    assert (
        await db_session.scalar(
            select(OwnerPreference).where(
                OwnerPreference.key.startswith(questions.PREFIX)
            )
        )
        is None
    )


async def test_narrative_uses_only_authorized_cohere_without_changing_global_provider_or_holding_owner_transaction(
    db_session, upload_case, monkeypatch
):
    from types import SimpleNamespace

    from backend.app.services.applications.answer_builder import AnswerBuilder

    case = upload_case
    ctx, item = await entered(db_session, case)
    await inspect(
        db_session, case, ctx, item, step("Why do you want to join this company?")
    )
    seen = []

    async def fake_build(self, *args, **kwargs):
        assert not self.answer_service.repo.session.in_transaction()
        seen.append(
            (
                self.answer_service.settings.LLM_PROVIDER,
                kwargs["generate"],
                kwargs["rewrite"],
            )
        )
        # Even apparently valid prose without grounded evidence must be rejected.
        return SimpleNamespace(
            validation_status="draft_ready",
            effective_answer="Unverified prose",
            provenance=SimpleNamespace(source="cohere", evidence_references=[]),
        )

    monkeypatch.setattr(AnswerBuilder, "build", fake_build)
    settings = case.settings.model_copy(
        update={
            "LLM_PROVIDER": "gemini",
            "COHERE_ENABLED": True,
            "COHERE_CANDIDATE_DATA_AUTHORIZED": True,
        }
    )
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    assert await forms.prepare_one(factory, settings)
    assert seen == [("cohere", True, True)] and settings.LLM_PROVIDER == "gemini"
    value = (await queue.load(db_session, item["id"])).value
    assert not value.get("questionnaire_answer") and value["status"] == "waiting"


async def test_grounded_project_context_change_invalidates_a_prepared_answer(
    db_session, upload_case, monkeypatch
):
    from backend.app.agent.tools import ToolDenied
    from backend.app.browser import service

    ctx, item, work, _ = await answered_ready(db_session, upload_case)
    row = await queue.load(db_session, item["id"])
    assert row.value["questionnaire_answer"]["project_digest"]

    async def changed(_session):
        return "changed-projects"

    monkeypatch.setattr(service, "project_stamp", changed)
    with pytest.raises(ToolDenied, match="questionnaire_grounded_context_changed"):
        await forms.context(db_session, row.value, upload_case.settings, writing=True)
