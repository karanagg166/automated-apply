"""Fictional imports/owner messages only; real HTTP is denied by conftest."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.app.agent.tools import ToolDenied
from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import questions, store
from backend.app.execution.contracts import Configuration, ImportJob
from backend.app.execution.naukri import capability_matrix, normalize, normalized_url
from backend.app.execution.telegram_commands import command
from backend.app.execution.worker import eligibility, prepare, watch
from backend.app.models.application_packet import ApplicationPacketField
from backend.app.schemas.applications import AnswerEdit, CreatePacket, QuestionInput
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.job_ingestion import JobIngestionService

URL = "https://www.naukri.com/job-listings-fictional-backend-281026123456"


@pytest.fixture
def owner_settings():
    return Settings(
        _env_file=None, TELEGRAM_OWNER_USER_ID=123, TELEGRAM_OWNER_CHAT_ID=456
    )


def message(reply_id=101, answer="Yes", owner=123):
    return {
        "from": {"id": owner},
        "chat": {"id": 456, "type": "private"},
        "text": answer,
        "reply_to_message": {"message_id": reply_id},
    }


@pytest.fixture
async def execution_target(db_session, phase2_profile):
    item = normalize(
        ImportJob(
            url=URL,
            title="Backend Developer",
            employer="Fictional Circuit",
            required_skills=["Python"],
            preferred_skills=["Rust"],
            location="India",
            remote_type="remote",
            experience_min=0.0,
            experience_max=3.0,
            experience_requirement="required",
        )
    )
    result = await JobIngestionService(db_session).ingest_jobs([item])
    await db_session.commit()
    return UUID(result.job_ids[0])


def test_matrix_does_not_claim_live():
    m = capability_matrix()
    assert m["live_verified"] is False
    assert "no_live_acceptance" in m["submission_support"]
    assert m["public_jobseeker_api"] == "not_established"
    assert m["background_source"].endswith("not_live_accepted")
    assert m["recurring_submission"]["state"] == "BLOCKED_TECHNICAL"
    assert m["recurring_submission"]["platform_permission_status"] == "not_established"
    assert m["recurring_submission"]["owner_requires_provider_outreach"] is False
    assert m["recurring_submission"]["enabled"] is False
    assert m["resume_upload"]["native_chooser_path"] == "NEEDS_HUMAN"
    assert m["resume_upload"]["file_selection_may_submit"] is True
    assert m["resume_upload"]["unattended_worker_verified"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://www.naukri.com/login",
        "https://naukri.com.attacker.example/job-listings-a-281026123456",
        "http://www.naukri.com/job-listings-a-281026123456",
        "https://user:pw@www.naukri.com/job-listings-a-281026123456",  # pragma: allowlist secret -- fictional rejected URL
        "https://127.0.0.1/job-listings-a-281026123456",
        "https://www.naukri.com/redirect?url=x",
        "https://www.naukri.com:8443/job-listings-a-281026123456",
    ],
)
def test_invalid_or_account_urls_denied(url):
    with pytest.raises(ValueError):
        normalized_url(url)


def test_tracking_removed_and_alert_reference_required():
    assert normalized_url(URL + "?src=alert#top") == URL
    with pytest.raises(ValueError):
        normalize(
            ImportJob(
                url=URL,
                title="SDE-1",
                employer="Fictional",
                provenance="owner_job_alert",
            )
        )
    item = normalize(
        ImportJob(
            url=URL,
            title="SDE-1",
            employer="Fictional",
            provenance="owner_job_alert",
            message_reference="owner-export-001",
        )
    )
    assert item.source_verification_status == "requires_review"
    assert item.data_provenance["provider_verified"] is False


@pytest.mark.asyncio
async def test_import_dedup_and_exactly_once_intent(db_session, execution_target):
    first = await store.start(db_session, [execution_target, execution_target])
    await db_session.commit()
    second = await store.start(db_session, [execution_target])
    assert len(first) == 1 and first[0]["attempt_id"] == second[0]["attempt_id"]
    assert len(await store.rows(db_session)) == 1
    assert all(
        len(k) <= 50
        for k in (await db_session.scalars(select(OwnerPreference.key))).all()
    )
    again = await JobIngestionService(db_session).ingest_jobs(
        [
            normalize(
                ImportJob(
                    url=URL + "?src=another",
                    title="Backend Developer",
                    employer="Fictional Circuit",
                )
            )
        ]
    )
    assert again.duplicate_count == 1 and again.job_ids == [str(execution_target)]


@pytest.mark.asyncio
async def test_default_and_mode_gates(db_session, execution_target):
    assert (await store.configuration(db_session)).mode == "ON_DEMAND"
    for config in [
        Configuration(mode="AUTO_APPLY_WHEN_AUTHORIZED"),
        Configuration(submission_permission=True),
        Configuration(destinations=["https://www.naukri.com"]),
    ]:
        with pytest.raises(ToolDenied):
            await store.configure(db_session, config)
    await store.configure(db_session, Configuration(mode="OFF"))
    await db_session.flush()
    assert await store.claim(db_session) is None
    with pytest.raises(ToolDenied):
        await store.start(db_session, [execution_target])


@pytest.mark.asyncio
async def test_lease_expiry_fence_heartbeat_and_cancel(db_session, execution_target):
    execution = (await store.start(db_session, [execution_target]))[0]
    identity = await store.claim(db_session)
    await db_session.flush()
    assert await store.claim(db_session) is None
    await store.heartbeat(db_session, identity)
    await db_session.flush()
    row = await store.load(db_session, execution["id"])
    row.value = {
        **row.value,
        "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.flush()
    recovered = await store.claim(db_session)
    assert recovered[1] > identity[1]
    with pytest.raises(ToolDenied):
        await store.fenced(db_session, identity)
    row = await store.load(db_session, execution["id"])
    await store.control(db_session, execution["id"], "cancel", row.value["revision"])
    await db_session.flush()
    with pytest.raises(ToolDenied):
        await store.fenced(db_session, recovered)
    assert (await store.load(db_session, execution["id"])).value[
        "state"
    ] == "FAILED_FINAL"


@pytest.mark.asyncio
async def test_pause_resume_and_revision_conflict(db_session, execution_target):
    e = (await store.start(db_session, [execution_target]))[0]
    paused = await store.control(db_session, e["id"], "pause", e["revision"])
    await db_session.flush()
    assert await store.claim(db_session) is None
    with pytest.raises(ToolDenied):
        await store.control(db_session, e["id"], "resume", 1)
    resumed = await store.control(db_session, e["id"], "resume", paused["revision"])
    assert resumed["state"] == "DISCOVERED"


@pytest.mark.parametrize(
    ("kind", "years", "lower", "upper", "expected"),
    [
        ("required", 0, 0, 1, "ELIGIBLE"),
        ("required", 1, 0, 1, "ELIGIBLE"),
        ("required", 0, 2, 4, "REJECTED"),
        ("preferred", 0, 2, 4, "ELIGIBLE"),
        ("unknown", 0, None, None, "NEEDS_INPUT"),
        ("required", None, 0, 1, "NEEDS_INPUT"),
    ],
)
def test_required_preferred_unknown_experience(kind, years, lower, upper, expected):
    job = SimpleNamespace(
        discovery_metadata={
            "experience_min_years": lower,
            "experience_max_years": upper,
            "data_provenance": {"experience_requirement": kind},
        }
    )
    match = SimpleNamespace(
        exclusion_reasons=[],
        matched_skills=["Python"],
        missing_skills=[],
        match_score=80,
    )
    assert (
        eligibility(job, SimpleNamespace(verified_experience_years=years), match)[0]
        == expected
    )


@pytest.mark.asyncio
async def test_on_demand_prepare_and_previous_application(db_session, execution_target):
    from backend.app.models.job import Job

    await store.start(db_session, [execution_target])
    identity = await store.claim(db_session)
    await prepare(db_session, identity)
    await db_session.flush()
    row = await store.load(db_session, identity[0])
    assert row.value["state"] == "NEEDS_INPUT"  # No confirmed resume in this fixture.
    assert row.value["packet_id"] and row.value["profile_version"]
    assert row.value["history"][0]["to"] == "MATCHED"
    job = await db_session.get(Job, execution_target)
    job.status = "applied"
    assert await store.previously_applied(db_session, job)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(OwnerPreference)
            .where(OwnerPreference.key.startswith("exec_event:"))
        )
        >= 3
    )


@pytest.mark.asyncio
async def test_saved_import_watch_is_opt_in_and_notifies_once(
    db_session, execution_target
):
    assert await watch(db_session) == 0
    await store.configure(db_session, Configuration(mode="WATCH_AND_NOTIFY"))
    await db_session.flush()
    assert await watch(db_session) == 1
    await db_session.flush()
    assert await watch(db_session) == 0
    assert not await store.rows(db_session)


@pytest.fixture
async def question_target(db_session, execution_target):
    execution = (await store.start(db_session, [execution_target]))[0]
    service = ApplicationPacketService(db_session)
    packet = await service.create(
        execution_target,
        CreatePacket(
            idempotency_key="question-fixture-01",
            questions=[
                QuestionInput(
                    question="Are you comfortable interviewing next week?",
                    max_characters=200,
                ),
                QuestionInput(
                    question="Are you willing to relocate?",
                    field_type="yes_no",
                    options=["Yes", "No"],
                ),
            ],
        ),
    )
    row = await store.load(db_session, execution["id"])
    row.value = {**row.value, "state": "NEEDS_INPUT", "packet_id": str(packet.id)}
    await db_session.flush()
    return row.value, packet


@pytest.mark.asyncio
async def test_question_owner_reply_correlation_and_provenance(
    db_session, question_target, owner_settings
):
    execution, packet = question_target
    field = packet.fields[-1]
    q = await questions.ask(db_session, execution["id"], field.id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    row.value = {**q, "state": "sent", "message_ids": [101]}
    await db_session.flush()
    with pytest.raises(ToolDenied):
        await questions.receive(db_session, owner_settings, message(owner=999), 1)
    assert (
        await questions.receive(db_session, owner_settings, message(reply_id=102), 2)
        is None
    )
    answer = await questions.receive(db_session, owner_settings, message(), 3)
    assert "Answer saved" in answer
    await db_session.flush()
    stored = await db_session.get(ApplicationPacketField, field.id)
    assert stored.human_answer == "Yes"
    assert stored.provenance["telegram_owner_update"] == 3
    assert stored.review_status == "pending"
    assert (await store.load(db_session, execution["id"])).value["state"] == "PREPARING"
    assert not row.value["reuse_approved"]
    assert "already answered" in await questions.receive(
        db_session, owner_settings, message(), 4
    )
    assert (await questions.approve_reuse(db_session, UUID(q["id"])))["reuse_approved"]


@pytest.mark.parametrize(
    "answer",
    [
        "next week",
        "Yes",
        "2020-01-01T10:00 Asia/Kolkata",
        "2030-01-01T10:00 Bad/Zone",
        "2026-11-01T10:00+05:30 Asia/Kolkata",
    ],
)
def test_availability_requires_dates_and_timezone(answer):
    q = {
        "question": "Interview availability",
        "answer_type": "availability",
        "options": [],
        "max_characters": 200,
    }
    with pytest.raises(ToolDenied):
        questions.validate(q, answer, datetime(2026, 10, 28, tzinfo=timezone.utc))


def test_availability_expiration():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    q = {
        "question": "Interview availability",
        "answer_type": "availability",
        "options": [],
        "max_characters": 200,
    }
    expiry = datetime.fromisoformat(
        questions.validate(q, "2026-11-02T14:00 Asia/Kolkata", now)
    )
    assert now < expiry <= now + timedelta(days=7)


@pytest.mark.asyncio
async def test_telegram_commands_share_intent_and_controls(
    db_session, execution_target
):
    assert "no portal search" in await command(db_session, "/naukri find")
    result = await command(db_session, "/naukri apply " + str(execution_target))
    assert "DISCOVERED" in result
    row = (await store.rows(db_session))[0]
    assert "PAUSED" in await command(db_session, "/naukri pause " + row.value["id"])
    assert "DISCOVERED" in await command(
        db_session, "/naukri resume " + row.value["id"]
    )
    assert "FAILED_FINAL" in await command(
        db_session, "/naukri cancel " + row.value["id"]
    )
    assert "Live installed acceptance pending" in await command(
        db_session, "/naukri status"
    )


@pytest.mark.asyncio
async def test_outbox_is_replayable_and_ack_idempotent(db_session, execution_target):
    await store.start(db_session, [execution_target])
    await db_session.flush()
    first = await store.events(db_session)
    assert first == await store.events(db_session) and len(first) == 1
    await store.acknowledge(db_session, UUID(first[0]["id"]))
    await store.acknowledge(db_session, UUID(first[0]["id"]))
    await db_session.flush()
    assert await store.events(db_session) == []


@pytest.mark.asyncio
async def test_ambiguous_submission_is_not_replayed(db_session, execution_target):
    execution = (await store.start(db_session, [execution_target]))[0]
    row = await store.load(db_session, execution["id"])
    row.value = {
        **row.value,
        "state": "SUBMITTING",
        "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.flush()
    assert await store.claim(db_session) is None
    assert (await store.load(db_session, execution["id"])).value[
        "state"
    ] == "SUBMISSION_UNKNOWN"


@pytest.mark.asyncio
async def test_no_naukri_submission_transition_or_fabricated_confirmation(
    db_session, execution_target
):
    execution = (await store.start(db_session, [execution_target]))[0]
    row = await store.load(db_session, execution["id"])
    for state in ["SUBMITTING", "SUBMITTED_CONFIRMED"]:
        with pytest.raises(ToolDenied, match="not_verified"):
            await store.move(db_session, row, state)


@pytest.mark.asyncio
async def test_concurrent_questions_for_same_packet_are_independent(
    db_session, question_target, owner_settings
):
    execution, packet = question_target
    first = await questions.ask(db_session, execution["id"], packet.fields[-2].id)
    second = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    for q, mid in [(first, 101), (second, 102)]:
        row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
        row.value = {**q, "state": "sent", "message_ids": [mid]}
    await db_session.flush()
    assert "rejected" in await questions.receive(
        db_session, owner_settings, message(answer="next week"), 4
    )
    date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT14:00")
    assert "saved" in await questions.receive(
        db_session, owner_settings, message(answer=date + " Asia/Kolkata"), 5
    )
    await db_session.flush()
    assert (await store.load(db_session, execution["id"])).value[
        "state"
    ] == "NEEDS_INPUT"
    assert "saved" in await questions.receive(
        db_session, owner_settings, message(reply_id=102), 6
    )
    await db_session.flush()
    assert (await store.load(db_session, execution["id"])).value["state"] == "PREPARING"


@pytest.mark.asyncio
async def test_expired_question_or_cancelled_execution_cannot_resume(
    db_session, question_target, owner_settings
):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    row.value = {
        **q,
        "state": "sent",
        "message_ids": [101],
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.flush()
    assert "expired" in await questions.receive(
        db_session, owner_settings, message(), 1
    )
    row.value = {
        **row.value,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    await db_session.flush()
    execution_row = await store.load(db_session, execution["id"])
    await store.control(
        db_session, execution["id"], "cancel", execution_row.value["revision"]
    )
    await db_session.flush()
    assert "cancelled" in await questions.receive(
        db_session, owner_settings, message(), 2
    )
    saved = await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    assert saved.human_answer is None


@pytest.mark.asyncio
async def test_stale_packet_does_not_accept_reply(
    db_session, question_target, owner_settings
):
    from backend.app.schemas.applications import QuestionsAdd

    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    row.value = {**q, "state": "sent", "message_ids": [101]}
    await ApplicationPacketService(db_session).add_questions(
        packet.id,
        QuestionsAdd(
            expected_revision=packet.revision,
            questions=[QuestionInput(question="New question")],
        ),
    )
    await db_session.flush()
    assert "context changed" in await questions.receive(
        db_session, owner_settings, message(), 4
    )


@pytest.mark.asyncio
async def test_gateway_api_auth_and_capability_contract(async_client, phase2_auth):
    response = await async_client.get("/api/v1/execution/naukri")
    assert response.status_code == 401
    response = await async_client.get("/api/v1/execution/naukri", headers=phase2_auth)
    assert response.status_code == 200
    assert response.json()["configuration"]["mode"] == "ON_DEMAND"
    response = await async_client.put(
        "/api/v1/execution/naukri",
        json={"mode": "AUTO_APPLY_WHEN_AUTHORIZED"},
        headers=phase2_auth,
    )
    assert response.status_code == 409
    response = await async_client.post(
        "/api/v1/execution/naukri/submit", headers=phase2_auth
    )
    assert response.status_code in {404, 405}
    response = await async_client.post(
        f"/api/v1/execution/questions/{uuid4()}/answer",
        json={"answer": "Yes", "expected_revision": 1},
        headers=phase2_auth,
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "text",
    [
        "password is hunter2",
        "api_key=fictional",
        "-----BEGIN " + "PRIVATE KEY-----",
    ],
)
def test_sensitive_answers_not_retained(text):
    q = {
        "question": "Tell us about yourself",
        "answer_type": "text",
        "options": [],
        "max_characters": 1000,
    }
    with pytest.raises(ValueError):
        questions.validate(q, text, datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_retry_exhaustion_is_terminal(db_session, execution_target):
    e = (await store.start(db_session, [execution_target]))[0]
    row = await store.load(db_session, e["id"])
    row.value = {**row.value, "attempts": 3}
    await db_session.flush()
    assert await store.claim(db_session) is None
    assert (await store.load(db_session, e["id"])).value["diagnostic"] == "retry_limit"


@pytest.mark.asyncio
async def test_reuse_requires_explicit_unexpired_permission(
    db_session, question_target
):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    with pytest.raises(ToolDenied):
        await questions.reuse_for(
            db_session, q["id"], execution["id"], packet.fields[-1].id
        )


@pytest.mark.asyncio
async def test_naukri_form_question_bridge_and_reviewed_answer_fill(
    db_session, execution_target, phase2_profile, owner_settings
):
    from backend.app.browser.contracts import Inspection
    from backend.app.browser.service import FormService
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.models.application_answer import CandidateResource
    from backend.app.schemas.applications import ReviewInput
    from backend.app.services.applications.review import ApplicationReview

    db_session.add(
        CandidateResource(
            candidate_profile_id=phase2_profile.id,
            resource_type="resume",
            label="Fictional PDF",
            url="https://example.org/resume.pdf",
            is_primary=True,
            user_confirmed=True,
        )
    )
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    await db_session.commit()
    service = ApplicationPacketService(db_session)
    packet = await service.create(
        execution_target, CreatePacket(idempotency_key="naukri-native-fixture")
    )
    await db_session.commit()
    form = FormService(db_session, Settings(_env_file=None, BROWSER_FILL_ENABLED=True))
    observation = Inspection(
        document_id=str(uuid4()),
        url=URL,
        fields=[
            {
                "field_id": "f0",
                "kind": "text",
                "label": "Are you willing to relocate?",
                "required": True,
            }
        ],
    )
    plan = await form.inspect(packet.id, observation, "manual_extension")
    await db_session.commit()
    assert plan.actions[0].needs_input
    qs = (
        await db_session.scalars(
            select(OwnerPreference).where(
                OwnerPreference.key.startswith(questions.PREFIX)
            )
        )
    ).all()
    assert len(qs) == 0  # Inspection cannot authorize a Telegram notification.
    current = await service.read(packet.id)
    field = next(f for f in current.fields if f.question == observation.fields[0].label)
    intent = await store.packet_question_intent(db_session, current)
    await questions.ask(db_session, intent["id"], field.id)  # Explicit owner Ask.
    await db_session.flush()
    qs = (await db_session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith(questions.PREFIX)
    ))).all()
    assert len(qs) == 1
    q = qs[0].value
    qs[0].value = {**q, "state": "sent", "message_ids": [101]}
    await db_session.flush()
    assert "saved" in await questions.receive(db_session, owner_settings, message(), 9)
    await db_session.commit()
    current = await service.read(packet.id)
    field = next(f for f in current.fields if f.question == observation.fields[0].label)
    await ApplicationReview(service).review(
        packet.id,
        ReviewInput(
            expected_revision=current.revision,
            action="review",
            reviewed_field_ids=[field.id],
        ),
    )
    await db_session.commit()
    reinspection = await form.inspect(
        packet.id,
        observation.model_copy(update={"document_id": str(uuid4())}),
        "manual_extension",
    )
    assert reinspection.actions[0].value == "Yes"
    assert reinspection.actions[0].evidence[0].startswith("reviewed_packet_answer:")
    assert reinspection.actions[0].requires_review
    await db_session.commit()
    saved = await db_session.get(ApplicationPacketField, field.id)
    saved.provenance = {
        **saved.provenance,
        "answer_expires_at": (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat(),
    }
    await db_session.commit()
    with pytest.raises(ToolDenied, match="stale"):
        await form.fresh(reinspection)
    assert (await service.read(packet.id)).readiness.state == "needs_input"


@pytest.mark.asyncio
async def test_two_employers_do_not_cross_resolve(
    db_session, execution_target, question_target, owner_settings
):
    from backend.app.models.job import Job

    execution, packet = question_target
    other = Job(
        title="Backend Developer",
        source_platform="naukri",
        job_url=URL.replace("123456", "123457"),
    )
    db_session.add(other)
    await db_session.flush()
    other_execution = (await store.start(db_session, [other.id]))[0]
    other_packet = await ApplicationPacketService(db_session).create(
        other.id,
        CreatePacket(
            idempotency_key="other-question",
            questions=[QuestionInput(question="Are you willing to relocate?")],
        ),
    )
    other_row = await store.load(db_session, other_execution["id"])
    other_row.value = {
        **other_row.value,
        "packet_id": str(other_packet.id),
        "state": "NEEDS_INPUT",
    }
    await db_session.flush()
    qs = [
        await questions.ask(db_session, execution["id"], packet.fields[-1].id),
        await questions.ask(
            db_session, other_execution["id"], other_packet.fields[-1].id
        ),
    ]
    await db_session.flush()
    for q, mid in zip(qs, [101, 102]):
        row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
        row.value = {**q, "state": "sent", "message_ids": [mid]}
    await db_session.commit()
    assert "saved" in await questions.receive(
        db_session, owner_settings, message(reply_id=102, answer="No"), 12
    )
    await db_session.commit()
    assert (
        await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    ).human_answer is None
    assert (
        await db_session.get(ApplicationPacketField, other_packet.fields[-1].id)
    ).human_answer == "No"
    assert (await store.load(db_session, execution["id"])).value[
        "state"
    ] == "NEEDS_INPUT"


def test_interview_choice_captures_schedule_without_filling_datetime_into_yes_no():
    q = {
        "question": "Comfortable interviewing next week?",
        "answer_type": "availability",
        "options": ["Yes", "No"],
        "max_characters": 3,
    }
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    text = "Yes | 2026-11-02T14:00 Asia/Kolkata"
    assert questions.field_answer(q, text) == "Yes"
    assert datetime.fromisoformat(questions.validate(q, text, now)) > now
    with pytest.raises(ToolDenied):
        questions.validate(q, "Yes", now)
    assert questions.validate(q, "No", now)


@pytest.mark.asyncio
async def test_requisition_intent_survives_changed_posting_slug(
    db_session, execution_target
):
    from backend.app.models.job import Job

    initial = (await store.start(db_session, [execution_target]))[0]
    other = Job(
        title="Changed title",
        source_platform="naukri",
        job_url=URL.replace("fictional-backend", "changed-title"),
    )
    db_session.add(other)
    await db_session.flush()
    again = (await store.start(db_session, [other.id]))[0]
    assert again["attempt_id"] == initial["attempt_id"]


@pytest.mark.asyncio
async def test_question_delivery_restart_and_unknown_ack_are_safe(
    db_session, question_target, owner_settings
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.local_agent.telegram import TelegramError

    test_session_factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )

    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.commit()

    class Bot:
        def __init__(self):
            self.calls = []
            self.fail = True

        async def call(self, method, payload):
            self.calls.append((method, payload))
            if self.fail:
                raise TelegramError("telegram_network_or_response_error")
            return {"message_id": 103}

    bot = Bot()
    with pytest.raises(TelegramError):
        await questions.deliver_one(test_session_factory, owner_settings, bot)
    async with test_session_factory() as session, session.begin():
        row = await session.get(OwnerPreference, questions.PREFIX + q["id"])
        assert row.value["delivery_lease"] and row.value["message_ids"] == []
        row.value = {
            **row.value,
            "delivery_lease": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat(),
        }
    bot.fail = False
    assert not await questions.deliver_one(test_session_factory, owner_settings, bot)
    assert len(bot.calls) == 1  # Telegram has no idempotency key; never guess/resend.
    payload = bot.calls[0][1]
    assert payload["chat_id"] == owner_settings.TELEGRAM_OWNER_CHAT_ID
    assert q["question"] in payload["text"] and execution["id"] in payload["text"]
    async with test_session_factory() as session:
        row = await session.get(OwnerPreference, questions.PREFIX + q["id"])
        assert row.value["message_ids"] == [] and row.value["state"] == "delivery_unknown"
        assert (await store.load(session, execution["id"])).value["state"] == "NEEDS_INPUT"



@pytest.mark.asyncio
async def test_owner_answer_survives_sessions_and_worker_resume(
    db_session, question_target, owner_settings
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.execution.worker import ExecutionWorker

    test_session_factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )

    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    row.value = {**q, "state": "sent", "message_ids": [101]}
    await db_session.commit()
    async with test_session_factory() as session, session.begin():
        assert "saved" in await questions.receive(
            session, owner_settings, message(), 500
        )
    worker = ExecutionWorker(test_session_factory)
    assert await worker.tick()
    async with test_session_factory() as session:
        row = await store.load(session, execution["id"])
        assert (
            row.value["state"] == "NEEDS_INPUT"
        )  # Other factual answer and resume remain missing.
        field = await session.get(ApplicationPacketField, packet.fields[-1].id)
        assert (
            field.human_answer == "Yes"
            and field.provenance["telegram_owner_update"] == 500
        )


@pytest.mark.asyncio
async def test_owner_ui_boundary_rejects_extension_mode_mutation(
    async_client, phase2_auth
):
    response = await async_client.put(
        "/api/v1/execution/naukri",
        headers={**phase2_auth, "X-Agent-Client": "fictional-extension"},
        json={"mode": "WATCH_AND_NOTIFY"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_history_read_before_owner_storage_migration_is_empty(db_session):
    from backend.app.integrations.gmail.history import reviewed_history
    from backend.app.knowledge.missing_input import storage_available

    async with db_session.bind.begin() as connection:
        await connection.run_sync(OwnerPreference.__table__.drop)
    assert await reviewed_history(db_session) == []
    assert not await storage_available(db_session)


@pytest.mark.asyncio
async def test_lost_fill_receipt_requires_reinspection_without_replay(
    db_session, execution_target
):
    execution = (await store.start(db_session, [execution_target]))[0]
    row = await store.load(db_session, execution["id"])
    row.value = {**row.value, "state": "READY_FOR_REVIEW"}
    plan = SimpleNamespace(id=uuid4())
    await store.fill_event(db_session, row, plan, "fill_authorized")
    await db_session.flush()
    assert await store.claim(db_session) is None
    row = await store.load(db_session, execution["id"])
    row.value = {
        **row.value,
        "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.flush()
    assert await store.claim(db_session) is None
    row = await store.load(db_session, execution["id"])
    assert row.value["state"] == "NEEDS_INPUT"
    assert row.value["diagnostic"] == "fill_outcome_unknown_reinspect_manually"
    await store.fill_event(db_session, row, plan, "form_filled")
    assert row.value["state"] == "NEEDS_INPUT"
    assert row.value["evidence"][-1]["submitted"] is False


@pytest.mark.asyncio
async def test_completed_fill_clears_lease_without_submission(
    db_session, execution_target
):
    execution = (await store.start(db_session, [execution_target]))[0]
    row = await store.load(db_session, execution["id"])
    row.value = {**row.value, "state": "READY_FOR_REVIEW"}
    plan = SimpleNamespace(id=uuid4())
    await store.fill_event(db_session, row, plan, "fill_authorized")
    await db_session.flush()
    await store.fill_event(db_session, row, plan, "form_filled")
    assert row.value["state"] == "READY_FOR_REVIEW" and row.value["lease_until"] is None
    assert all(e["submitted"] is False for e in row.value["evidence"])


@pytest.mark.asyncio
async def test_expired_answer_requires_explicit_reconfirmation_and_accepts_only_current_reply(
    db_session, question_target, owner_settings
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.execution.worker import ExecutionWorker

    execution, packet = question_target
    original = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    qrow = await db_session.get(OwnerPreference, questions.PREFIX + original["id"])
    qrow.value = {**original, "state": "sent", "message_ids": [101]}
    await db_session.flush()
    assert "saved" in await questions.receive(
        db_session, owner_settings, message(), 900
    )
    await db_session.commit()
    field = await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    field.provenance = {
        **field.provenance,
        "answer_expires_at": (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat(),
    }
    row = await store.load(db_session, execution["id"])
    row.value = {**row.value, "state": "READY_FOR_REVIEW"}
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    await ExecutionWorker(factory).tick()
    await db_session.rollback()
    unapproved = (await db_session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith(questions.PREFIX)
    ))).all()
    assert not any(r.value["state"] == "pending" for r in unapproved)
    await questions.ask(db_session, execution["id"], field.id)
    await db_session.flush()
    pending = (
        await db_session.scalars(
            select(OwnerPreference).where(
                OwnerPreference.key.startswith(questions.PREFIX)
            )
        )
    ).all()
    replacement = next(
        r
        for r in pending
        if r.value["field_id"] == str(field.id) and r.value["state"] == "pending"
    )
    assert replacement.value["id"] != original["id"]
    replacement.value = {**replacement.value, "state": "sent", "message_ids": [202]}
    await db_session.commit()
    assert "already answered" in await questions.receive(
        db_session, owner_settings, message(reply_id=101, answer="No"), 901
    )
    assert "saved" in await questions.receive(
        db_session, owner_settings, message(reply_id=202, answer="No"), 902
    )
    await db_session.commit()
    refreshed = await db_session.get(
        ApplicationPacketField, field.id, populate_existing=True
    )
    assert refreshed.human_answer == "No"
    assert datetime.fromisoformat(
        refreshed.provenance["answer_expires_at"]
    ) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_expired_unanswered_question_reissues_without_accepting_old_message(
    db_session, question_target, owner_settings
):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    row.value = {
        **q,
        "state": "sent",
        "message_ids": [101],
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    await db_session.commit()
    renewed = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    assert renewed["state"] == "pending" and renewed["message_ids"] == []
    assert renewed["expired_message_ids"] == [101]
    assert "latest question" in await questions.receive(
        db_session, owner_settings, message(), 903
    )
    assert (
        await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    ).human_answer is None


def test_optional_expired_answer_also_requires_reconfirmation():
    from backend.app.execution.worker import needs_owner_answer

    now = datetime.now(timezone.utc)
    field = SimpleNamespace(
        required=False,
        effective_answer="Earlier owner answer",
        field_type="text",
        provenance=SimpleNamespace(answer_expires_at=now - timedelta(seconds=1)),
    )
    assert needs_owner_answer(field, now)


@pytest.mark.asyncio
async def test_dashboard_answer_updates_packet_and_advances_execution(
    db_session, question_target
):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    result = await questions.answer_dashboard(db_session, q["id"], "Yes", q["packet_revision"])
    assert result["state"] == "answered"
    assert result["answer"] == "Yes"
    assert result["provenance"]["channel"] == "dashboard"

    field = await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    assert field.human_answer == "Yes"
    assert field.provenance["telegram_question"] == q["id"]

    row = await store.load(db_session, execution["id"])
    assert row.value["state"] == "PREPARING"


@pytest.mark.asyncio
async def test_dashboard_answer_requires_fresh_revision_and_review_and_cannot_replay(
    db_session, question_target, owner_settings
):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.commit()
    with pytest.raises(ToolDenied, match="question_revision_conflict"):
        await questions.answer_dashboard(db_session, q["id"], "Yes", q["packet_revision"] + 1)
    await questions.answer_dashboard(db_session, q["id"], "Yes", q["packet_revision"])
    await db_session.commit()
    db_session.expunge_all()  # Recover only from durable state, as after restart.
    field = await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    assert field.human_answer == "Yes" and field.review_status == "pending"
    saved = await ApplicationPacketService(db_session).read(packet.id)
    assert saved.approved_revision is None
    row = await store.load(db_session, execution["id"])
    assert row.value["state"] == "PREPARING"
    assert not row.value.get("approved_answer_revisions")
    with pytest.raises(ToolDenied, match="question_already_answered"):
        await questions.answer_dashboard(db_session, q["id"], "No", q["packet_revision"])
    assert field.human_answer == "Yes"


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["expired", "paused", "cancelled", "stale", "other_packet", "invalid_choice"])
async def test_dashboard_answer_rejects_invalid_or_stale_context(db_session, question_target, condition):
    execution, packet = question_target
    q = await questions.ask(db_session, execution["id"], packet.fields[-1].id)
    await db_session.flush()
    row = await db_session.get(OwnerPreference, questions.PREFIX + q["id"])
    intent = await store.load(db_session, execution["id"])
    if condition == "expired":
        row.value = {**q, "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    elif condition == "paused":
        intent.value = {**intent.value, "state": "PAUSED"}
    elif condition == "cancelled":
        intent.value = {**intent.value, "cancelled": True}
    elif condition == "other_packet":
        intent.value = {**intent.value, "packet_id": str(uuid4())}
    elif condition == "stale":
        await ApplicationPacketService(db_session).edit_answer(packet.id, packet.fields[-1].id, AnswerEdit(expected_revision=packet.revision, answer="No"))
    await db_session.flush()
    with pytest.raises(ToolDenied):
        await questions.answer_dashboard(db_session, q["id"], "Maybe" if condition == "invalid_choice" else "Yes", q["packet_revision"])
    field = await db_session.get(ApplicationPacketField, packet.fields[-1].id)
    assert field.human_answer == ("No" if condition == "stale" else None)
    assert row.value["state"] != "answered"


@pytest.mark.asyncio
async def test_dashboard_answer_owner_boundary_and_validation(async_client, phase2_auth):
    url = f"/api/v1/execution/questions/{uuid4()}/answer"
    payload = {"answer": "Yes", "expected_revision": 1}
    assert (await async_client.post(url, json=payload)).status_code == 401
    for extra in ({"X-Agent-Client": "extension"}, {"Origin": "chrome-extension://fictional"}):
        assert (await async_client.post(url, json=payload, headers={**phase2_auth, **extra})).status_code == 403
    for invalid in ({"answer": "Yes"}, {**payload, "expected_revision": 0}, {**payload, "expected_revision": "1"}, {**payload, "answer": "  "}, {**payload, "answer": "a" * 4001}, {**payload, "approved": True}):
        assert (await async_client.post(url, json=invalid, headers=phase2_auth)).status_code == 422


@pytest.mark.parametrize("changes", [
    {"experience_min": 4, "experience_max": 1},
    {"salary_min": 100, "salary_max": 10},
    {"employer": "   "}, {"title": "\t"},
    {"posting_status": "active"},
    {"posting_status": "active", "observed_at": "2099-01-01T00:00:00Z"},
    {"posting_status": "active", "observed_at": "2026-10-29T10:00:00"},
])
def test_reviewed_import_rejects_ambiguous_or_invalid_criteria(changes):
    with pytest.raises(ValueError):
        ImportJob.model_validate({"url": URL, "title": "Backend Engineer", "employer": "Fictional", **changes})


@pytest.mark.parametrize("path", ["a/nested", "a%2Fredirect", "a?next=x", "a#x"])
def test_naukri_posting_path_matches_extension_boundary(path):
    # Tracking on an actual posting is stripped; separators inside the path
    # cannot turn arbitrary account/navigation endpoints into postings.
    if path == "a%2Fredirect":
        # Percent-encoded slug text is allowed by the extension, too.
        assert normalized_url(f"https://www.naukri.com/job-listings-{path}-281026123456")
    else:
        with pytest.raises(ValueError):
            normalized_url(f"https://www.naukri.com/job-listings-{path}-281026123456")


@pytest.mark.asyncio
async def test_preparation_and_worker_tick_do_not_authorize_telegram(db_session, execution_target):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.execution.worker import ExecutionWorker

    await store.start(db_session, [execution_target])
    identity = await store.claim(db_session)
    await prepare(db_session, identity)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    await ExecutionWorker(factory).tick()
    assert not (await db_session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith(questions.PREFIX)
    ))).all()


@pytest.mark.asyncio
async def test_review_explains_unknown_experience_and_owner_observed_currentness(db_session, execution_target, phase2_profile):
    from backend.app.execution.naukri_review import review_jobs
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.models.job import Job

    job = await db_session.get(Job, execution_target)
    phase2_profile.verified_experience_years = None
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    await db_session.flush()
    review = (await review_jobs(db_session, [job]))[0]
    assert review["state"] == "NEEDS_INPUT"
    assert review["vacancy_review"] == "unverified"
    assert "experience_suitability" in review["match"]["unknown_fields"]
    assert review["submission_allowed"] is False
    assert review["provider_verified"] is False


@pytest.mark.asyncio
async def test_owner_applied_and_closed_observations_prevent_preparation(db_session, execution_target, phase2_profile):
    from backend.app.execution.naukri_review import review_jobs
    from backend.app.models.job import Job

    job = await db_session.get(Job, execution_target)
    for status in ["already_applied", "closed"]:
        job.discovery_metadata = {**job.discovery_metadata, "data_provenance": {
            "posting_status": status, "owner_observed_at": datetime.now(timezone.utc).isoformat()}}
        result = (await review_jobs(db_session, [job]))[0]
        assert result["state"] == "REJECTED"
        if status == "already_applied":
            assert await store.previously_applied(db_session, job)
        else:
            fit = SimpleNamespace(exclusion_reasons=[], matched_skills=["Python"], missing_skills=[], match_score=90)
            assert eligibility(job, phase2_profile, fit) == ("REJECTED", "vacancy_closed_expired_or_invalid")


def test_latest_imported_criteria_are_used_without_mutating_human_job_fields():
    from backend.app.execution.naukri import matching_job

    job = SimpleNamespace(title="Owner title", skills_required=["Python"], discovery_metadata={
        "source_name": "naukri", "title": "Backend Engineer", "skills_required": ["Rust"], "remote_type": "remote"})
    view = matching_job(job)
    assert view.title == "Backend Engineer" and view.skills_required == ["Rust"]
    assert job.title == "Owner title" and job.skills_required == ["Python"]


def test_currentness_expires_and_never_invents_provider_verification():
    from backend.app.execution.naukri_review import vacancy_review

    now = datetime.now(timezone.utc)
    for age, expected in [(timedelta(hours=1), "owner_observed_active"), (timedelta(days=2), "stale")]:
        item = normalize(ImportJob(url=URL, title="Backend", employer="Fictional",
            posting_status="active", observed_at=now-age))
        job = SimpleNamespace(discovery_metadata=item.model_dump(mode="json"), status="discovered", source_verification_status="requires_review")
        assert vacancy_review(job, now) == expected
        assert item.data_provenance["provider_verified"] is False


@pytest.mark.asyncio
async def test_reimported_criteria_and_expiry_invalidate_saved_packet_review(db_session, execution_target):
    from backend.app.models.job import Job

    service = ApplicationPacketService(db_session)
    packet = await service.create(execution_target, CreatePacket(idempotency_key="phase53-stale-criteria"))
    job = await db_session.get(Job, execution_target)
    original_title, original_skills = job.title, list(job.skills_required)
    job.discovery_metadata = {**job.discovery_metadata, "skills_required": ["Rust"],
        "data_provenance": {**job.discovery_metadata["data_provenance"], "valid_through": "2026-02-10"}}
    await db_session.flush()
    current = await service.read(packet.id)
    assert current.readiness.stale and current.approved_revision is None
    assert job.title == original_title and job.skills_required == original_skills
    assert not (await service.builder.context(job.id))[2].destination.valid


@pytest.mark.parametrize("expiry,expected", [("2026-02-10", "expired"), ("bad-date", "invalid_evidence")])
def test_vacancy_labels_distinguish_expiry_and_invalid_evidence(expiry, expected):
    from backend.app.execution.naukri_review import vacancy_review

    job = SimpleNamespace(status="discovered", source_verification_status="requires_review",
        discovery_metadata={"data_provenance": {"posting_status": "active", "valid_through": expiry}})
    assert vacancy_review(job, datetime(2026, 10, 29, tzinfo=timezone.utc)) == expected
