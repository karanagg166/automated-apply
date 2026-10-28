"""Fictional ATS packets use the existing owner reply outbox without a fill worker."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.execution import questions, store
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.schemas.applications import QuestionInput, QuestionsAdd
from backend.app.services.applications.service import ApplicationPacketService


@pytest.fixture
async def ats_question(async_client, phase2_auth, phase2_profile, db_session):
    response = await async_client.post(
        "/api/v1/application-packets/intake",
        headers=phase2_auth,
        json={
            "application_url": "https://job-boards.greenhouse.io/fictional/jobs/987654",
            "company_name": "Fictional ATS",
            "job_title": "Engineer",
            "idempotency_key": "fictional-ats-question-01",
        },
    )
    assert response.status_code == 201, response.text
    packet = await ApplicationPacketService(db_session).add_questions(
        UUID(response.json()["id"]),
        QuestionsAdd(
            expected_revision=response.json()["revision"],
            questions=[
                QuestionInput(
                    question="Are you willing to relocate?",
                    field_type="yes_no",
                    options=["Yes", "No"],
                )
            ],
        ),
    )
    await db_session.commit()
    return packet, packet.fields[-1]


@pytest.mark.asyncio
async def test_ats_owner_reply_survives_restart_without_worker_or_duplicate_fill(
    ats_question, async_client, phase2_auth, db_session
):
    packet, field = ats_question
    path = f"/api/v1/execution/packets/{packet.id}/questions/{field.id}"
    body = {"expected_revision": packet.revision}
    first = await async_client.post(path, headers=phase2_auth, json=body)
    assert first.status_code == 200, first.text
    repeated = await async_client.post(path, headers=phase2_auth, json=body)
    assert repeated.json()["id"] == first.json()["id"]
    q = first.json()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    settings = SimpleNamespace(TELEGRAM_OWNER_USER_ID=123, TELEGRAM_OWNER_CHAT_ID=456)

    class Bot:
        calls = 0

        async def call(self, method, payload):
            assert method == "sendMessage" and payload["chat_id"] == 456
            assert (
                q["execution_id"] in payload["text"]
                and field.question in payload["text"]
            )
            self.calls += 1
            return {"message_id": 42}

    bot = Bot()
    assert await questions.deliver_one(factory, settings, bot)
    assert not await questions.deliver_one(factory, settings, bot)
    message = {
        "from": {"id": 123},
        "chat": {"id": 456, "type": "private"},
        "reply_to_message": {"message_id": 42},
        "text": "Yes",
    }
    async with factory() as session, session.begin():
        assert (
            await questions.receive(
                session,
                settings,
                {**message, "reply_to_message": {"message_id": 41}},
                1,
            )
            is None
        )
        assert "saved" in await questions.receive(session, settings, message, 2)
    async with factory() as session, session.begin():
        assert "already answered" in await questions.receive(
            session, settings, message, 3
        )
        stored = await session.get(ApplicationPacketField, field.id)
        assert stored.human_answer == "Yes" and stored.review_status == "pending"
        current = await ApplicationPacketService(session).read(packet.id)
        assert current.approved_revision is None
        row = await store.load(session, q["execution_id"])
        assert (
            row.value["packet_id"] == str(packet.id)
            and row.value["state"] == "PREPARING"
        )
        assert row.value["question_only"] and row.value["attempts"] == 0
        assert await store.claim(session) is None
        for state in ("FILLING", "SUBMITTING", "SUBMITTED_CONFIRMED"):
            with pytest.raises(ToolDenied, match="question_context_cannot_execute"):
                await store.move(session, row, state)
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_ats_question_route_rejects_nonowner_stale_and_foreign_field(
    ats_question, async_client, phase2_auth
):
    packet, field = ats_question
    path = f"/api/v1/execution/packets/{packet.id}/questions/{field.id}"
    body = {"expected_revision": packet.revision}
    assert (await async_client.post(path, json=body)).status_code == 401
    assert (
        await async_client.post(
            path, headers={**phase2_auth, "X-Agent-Client": "extension"}, json=body
        )
    ).status_code == 403
    assert (
        await async_client.post(
            path, headers=phase2_auth, json={"expected_revision": packet.revision + 1}
        )
    ).status_code == 409
    assert (
        await async_client.post(
            f"/api/v1/execution/packets/{packet.id}/questions/{uuid4()}",
            headers=phase2_auth,
            json=body,
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_question_context_preserves_native_plan_authorization_and_owner_pause(
    ats_question, db_session
):
    from backend.app.dashboard.models import OwnerPreference

    packet, _ = ats_question
    intent = await store.packet_question_intent(db_session, packet)
    plan_id = uuid4()
    db_session.add(
        OwnerPreference(
            key=f"fill_plan:{plan_id}", value={"application_id": str(packet.id)}
        )
    )
    await db_session.flush()
    assert await store.lock_plan_execution(db_session, plan_id) is None
    await store.control(db_session, intent["id"], "pause", intent["revision"])
    with pytest.raises(ToolDenied, match="execution_paused_or_cancelled"):
        await store.lock_plan_execution(db_session, plan_id)
