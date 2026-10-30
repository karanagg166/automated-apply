"""Fictional full free workflow; HTTP is injected and no browser is opened."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.dashboard.models import Notification, OwnerPreference
from backend.app.execution import recurring, store
from backend.app.execution.contracts import AutomationControl
from backend.app.execution.notifications import notify_packet
from backend.app.execution.worker import ExecutionWorker
from backend.app.integrations.gmail import job_alerts as alerts
from backend.app.local_agent.models import TelegramDelivery
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.models.job import Job
from backend.app.schemas.applications import (
    AnswerEdit,
    QuestionInput,
    QuestionsAdd,
    SubmissionInput,
)
from backend.app.services.applications.review import ApplicationReview
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.applications.tracker import ApplicationTracker
from backend.tests.phase4a_fakes import GoogleFixture
from backend.tests.phase5a_fakes import approve
from backend.tests.test_local_gmail_discovery import LINK, message
from backend.tests.test_naukri_recurring import imported, start
from backend.tests.test_naukri_recurring import prepared_policy as prepared_policy
from backend.tests.test_naukri_reviewed_facts import reimport
from backend.tests.test_phase54_mailboxes import configured, connect


async def ready(session):
    await imported(session)
    await start(session)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False, autoflush=False)
    identity = await ExecutionWorker(factory).tick()
    session.expire_all()
    execution = await store.load(session, identity[0])
    service = ApplicationPacketService(session)
    return factory, execution, service, await service.read(UUID(execution.value["packet_id"]))


async def notices(session):
    return list((await session.scalars(select(Notification).where(
        Notification.kind == "application_ready"
    ).order_by(Notification.created_at))).all())


async def test_approved_alert_to_owner_handoff_and_manual_report(
    db_session, prepared_policy, async_client, phase2_auth
):
    """The portal boundary stays manual even when every local step succeeds."""
    settings, fake, calls = configured(), GoogleFixture(), []
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "gmail.googleapis.com"
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "mail1"}, {"id": "mail2"}]})
        return httpx.Response(200, json=message(request.url.path.rsplit("/", 1)[-1]))

    async with fake.client() as oauth, httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        mailbox, account, _ = await connect(db_session, settings, fake, oauth)
        await alerts.configure(db_session, settings, "1", alerts.AlertPolicy(
            expected_version=0, expected_generation=account["generation"], enabled=True))
        await start(db_session)
        await db_session.commit()

        def construct(session, config):
            return type(mailbox)(session, config, mailbox.google, client)

        result = await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        assert result["candidates_added"] == 1 and len(calls) == 5
        candidate = await db_session.scalar(select(OwnerPreference).where(
            OwnerPreference.key.startswith("nau_alert:")))
        assert candidate.value["employer"] is None and candidate.value["title"] is None
        assert len(candidate.value["message_references"]) == 2
        candidate_id = candidate.value["id"]
        # The owner supplies actual observed vacancy facts; no slug inference.
        await reimport(async_client, phase2_auth, LINK, alert_candidate_id=candidate_id)
        db_session.expire_all()
        candidate = await db_session.get(OwnerPreference, "nau_alert:" + candidate_id)
        assert candidate.value["state"] == "OWNER_REVIEWED"
        await db_session.commit()
        identity = await ExecutionWorker(factory).tick()
        assert identity
        db_session.expire_all()
        execution = await store.load(db_session, identity[0])
        service = ApplicationPacketService(db_session)
        packet = await service.read(UUID(execution.value["packet_id"]))
        assert packet.readiness.state == "needs_review"
        assert next(f.effective_answer for f in packet.fields if f.question == "Email") == "alex@example.com"
        assert len(await notices(db_session)) == 1
        assert "owner review" in (await notices(db_session))[0].title
        packet = await approve(service, packet)
        assert len(await notices(db_session)) == 2
        assert "manual Apply" in (await notices(db_session))[1].title
        handoff = await ApplicationReview(service).handoff(packet.id)
        assert handoff.submission_mode == "manual_handoff" and handoff.submitted is False
        assert packet.snapshot.resume.selected.resource_id == prepared_policy.resume_resource_id
        await notify_packet(db_session, execution, packet)
        assert len(await notices(db_session)) == 2  # same revision, retried delivery
        await db_session.commit()
        assert await ExecutionWorker(factory).tick() is None  # restart/cadence, no duplicate intent
        # A fixture owner report is never transformed into a provider receipt.
        report = await ApplicationTracker(service).report(packet.id, SubmissionInput(
            expected_revision=packet.revision, idempotency_key="fictional-owner-receipt-001",
            human_confirmed=True, confirmation="I submitted this application on the official website",
            receipt_reference="FICTIONAL owner-observed Applied Jobs status"))
        assert report.confirmation_source == "user_reported"
        assert report.evidence_confidence == "self_reported_unverified"
        job = await db_session.get(Job, packet.job_id)
        assert await store.previously_applied(db_session, job)
        assert job.status == "discovered"
        again = await alerts.poll(factory, settings, force=True, mailbox_factory=construct)
        assert again["candidates_added"] == 0 and len(calls) == 6
        assert not (await service.read(packet.id)).readiness.state == "ready_for_manual_handoff"


@pytest.mark.parametrize("blocker", ["stale", "missing", "expired", "paused", "stopped", "submitted", "unknown"])
async def test_readiness_notice_rejects_incomplete_or_fenced_work(db_session, prepared_policy, blocker):
    _, execution, service, packet = await ready(db_session)
    assert len(await notices(db_session)) == 1
    if blocker == "stale":
        packet.readiness.stale = True
    elif blocker in {"missing", "expired"}:
        field = next(f for f in packet.fields if f.question == "Email")
        if blocker == "missing":
            field.proposed_answer = None
            field.validation_status = "needs_input"
        else:
            field.provenance.answer_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif blocker == "paused":
        await store.control(db_session, execution.value["id"], "pause", execution.value["revision"])
    elif blocker == "stopped":
        value = await recurring.record(db_session)
        await recurring.control(db_session, AutomationControl(action="stop", expected_revision=value["revision"]))
    elif blocker == "submitted":
        packet.lifecycle_state = "user_reported_submitted"
    else:
        packet.lifecycle_state = "submission_unknown"
    packet.revision += 1  # a fresh key must still not publish
    assert await notify_packet(db_session, execution, packet) is False
    assert len(await notices(db_session)) == 1


async def test_real_unknown_question_needs_owner_answer_before_approval(db_session, prepared_policy):
    _, execution, service, packet = await ready(db_session)
    packet = await service.add_questions(packet.id, QuestionsAdd(
        expected_revision=packet.revision,
        questions=[QuestionInput(question="What is your expected annual salary?", field_type="text", required=True)]))
    field = packet.fields[-1]
    assert not field.effective_answer and packet.readiness.state == "needs_input"
    assert await notify_packet(db_session, execution, packet) is False
    packet = await service.edit_answer(packet.id, field.id, AnswerEdit(
        expected_revision=packet.revision, answer="INR 800000 annually"))
    saved = await db_session.get(ApplicationPacketField, field.id)
    assert saved.provenance["source"] == "human"
    assert packet.readiness.state == "needs_review"
    packet = await approve(service, packet)
    assert packet.readiness.state == "ready_for_manual_handoff"
    assert "manual Apply" in (await notices(db_session))[-1].title


@pytest.mark.parametrize("opted_in", [False, True])
async def test_telegram_outbox_requires_current_policy_opt_in_and_deduplicates(
    db_session, prepared_policy, monkeypatch, opted_in
):
    settings = configured(TELEGRAM_BOT_TOKEN="fictional", TELEGRAM_OWNER_CHAT_ID=456, TELEGRAM_OWNER_USER_ID=123)
    monkeypatch.setattr("backend.app.core.config.get_settings", lambda: settings)
    _, execution, service, packet = await ready(db_session)
    automation = await recurring.record(db_session)
    await recurring.put(db_session, recurring.KEY, {**automation, "policy": {
        **automation["policy"], "telegram_questions": opted_in}})
    packet = await approve(service, packet)
    await notify_packet(db_session, execution, packet)
    deliveries = list((await db_session.scalars(select(TelegramDelivery))).all())
    assert len(deliveries) == int(opted_in)
    if deliveries:
        assert deliveries[0].state == "pending"
        assert "No application has been sent" in deliveries[0].reply
        assert "manual Apply" in deliveries[0].reply


@pytest.mark.parametrize("preference", [{"in_app": False}, {"paused": True}])
async def test_ready_notice_respects_disabled_owner_notifications(db_session, prepared_policy, preference):
    _, execution, service, packet = await ready(db_session)
    db_session.add(OwnerPreference(key="notifications", value=preference))
    await db_session.flush()
    packet = await approve(service, packet)
    assert await notify_packet(db_session, execution, packet) is False
    assert len(await notices(db_session)) == 1


async def test_owner_created_packet_without_execution_gets_manual_handoff_notice(
    db_session, packet_service, application_target
):
    from backend.tests.phase5a_fakes import create

    job, _ = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    assert not await store.rows(db_session)
    alerts = await notices(db_session)
    assert len(alerts) == 1 and alerts[0].href == "/applications/" + str(packet.id)
    assert "manual Apply" in alerts[0].title
    assert not list((await db_session.scalars(select(TelegramDelivery))).all())
