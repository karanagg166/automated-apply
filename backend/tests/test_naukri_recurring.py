"""Isolated fictional records: these checks are not live Naukri acceptance."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import recurring, store
from backend.app.execution.contracts import (
    AutomationControl,
    AutomationPolicy,
    AutomationPolicyUpdate,
    Configuration,
    ImportJob,
)
from backend.app.execution.naukri import normalize
from backend.app.execution.telegram_commands import command
from backend.app.execution.worker import ExecutionWorker, prepare
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.app.services.job_ingestion import JobIngestionService


@pytest.fixture
async def prepared_policy(db_session, phase2_profile, application_target):
    phase2_profile.preferences = {
        "target_titles": ["Backend Developer"],
        "preferred_locations": ["India"],
        "notice_period_days": 30,
    }
    await db_session.flush()
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    fixture_job, _ = application_target
    fixture_job.source_platform = "fictional_fixture"
    await db_session.flush()
    _, confirmed, resume = await recurring.context(db_session)
    assert confirmed and resume
    policy = AutomationPolicy(
        profile_version=phase2_profile.version,
        resume_resource_id=resume.resource_id,
        resume_version=resume.resource_version,
        allowed_roles=["Backend Developer"],
        allowed_locations=["India"],
        experience_min=0,
        experience_max=3,
        minimum_match_score=80,
        interval_seconds=900,
        max_preparations_per_day=1,
    )
    await recurring.configure(
        db_session, AutomationPolicyUpdate(expected_revision=0, policy=policy)
    )
    return policy


async def start(session):
    value = await recurring.record(session)
    return await recurring.control(
        session, AutomationControl(action="start", expected_revision=value["revision"])
    )


async def imported(session, requisition="281026123456", **updates):
    item = ImportJob(
        url="https://www.naukri.com/job-listings-fictional-backend-" + requisition,
        title="Backend Developer",
        employer="Fictional Circuit",
        location="India",
        remote_type="remote",
        employment_type="full_time",
        description="Build Python backend APIs",
        required_skills=["Python"],
        experience_min=0,
        experience_max=3,
        experience_requirement="required",
        posting_status="active",
        observed_at=datetime.now(timezone.utc),
        posted_at=datetime.now(timezone.utc),
        **updates,
    )
    result = await JobIngestionService(session).ingest_jobs([normalize(item)])
    return UUID(result.job_ids[0])


@pytest.mark.asyncio
async def test_default_no_dispatch_start_requires_policy(db_session):
    await recurring.tick(db_session)
    assert await store.claim(db_session) is None
    view = await recurring.status(db_session)
    assert view["state"] == "STOPPED" and view["worker_online"]
    assert (
        not view["new_vacancy_discovery"] and view["counts"]["submitted_confirmed"] == 0
    )
    with pytest.raises(ToolDenied, match="bounded_preparation_policy_required"):
        await start(db_session)


@pytest.mark.asyncio
async def test_real_worker_tick_creates_packet_and_deduplicates(
    db_session, prepared_policy
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_session_factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )

    job_id = await imported(db_session)
    await start(db_session)
    await db_session.commit()
    identity = await ExecutionWorker(test_session_factory).tick()
    assert identity, [
        (d["reason"], d.get("match", {}).get("unknown_fields"))
        for d in (await recurring.status(db_session))["decisions"]
    ]
    db_session.expire_all()
    row = await store.load(db_session, identity[0])
    assert row.value["packet_id"] and row.value["state"] in {
        "NEEDS_INPUT",
        "READY_FOR_REVIEW",
    }
    packet = await db_session.get(ApplicationPacket, UUID(row.value["packet_id"]))
    assert packet.resume_resource_id == prepared_policy.resume_resource_id
    assert packet.job_id == job_id
    view = await recurring.status(db_session)
    assert (
        view["counts"]["prepared"] == 1 and view["counts"]["submitted_confirmed"] == 0
    )
    assert view["last_check_at"] and view["next_check_at"]
    assert await command(db_session, "/naukri status")
    # A second worker connection and process-local tick reuse DB cadence/intent.
    await db_session.commit()
    assert await ExecutionWorker(test_session_factory).tick() is None
    assert len(await store.rows(db_session)) == 1


@pytest.mark.asyncio
async def test_daily_cap_new_records_and_stop_fence(db_session, prepared_policy):
    first = await imported(db_session)
    await imported(db_session, "281026123457")
    running = await start(db_session)
    await recurring.tick(db_session)
    assert len(await store.rows(db_session)) == 1
    view = await recurring.status(db_session)
    assert any(d["reason"] == "daily_preparation_limit" for d in view["decisions"])
    claim = await store.claim(db_session)
    assert claim
    stopped = await recurring.control(
        db_session,
        AutomationControl(action="stop", expected_revision=running["revision"]),
    )
    with pytest.raises(ToolDenied):
        await store.fenced(db_session, claim)
    with pytest.raises(ToolDenied, match="stopped"):
        await store.start(db_session, [first])
    assert await store.claim(db_session) is None
    await start(db_session)
    assert await store.claim(db_session) is None  # Start never resumes owner pauses.
    with pytest.raises(ToolDenied, match="revision_conflict"):
        await recurring.control(
            db_session,
            AutomationControl(action="pause", expected_revision=stopped["revision"]),
        )

    row = (await store.rows(db_session))[0]
    resumed = await store.control(
        db_session, row.value["id"], "resume", row.value["revision"]
    )
    assert (
        resumed["automation_revision"]
        == (await recurring.record(db_session))["revision"]
    )
    assert await store.claim(db_session)


@pytest.mark.asyncio
async def test_recheck_stale_observation_after_claim(db_session, prepared_policy):
    job_id = await imported(db_session)
    await start(db_session)
    await recurring.tick(db_session)
    identity = await store.claim(db_session)
    job = await db_session.get(Job, job_id)
    meta = dict(job.discovery_metadata)
    meta["data_provenance"] = {
        **meta["data_provenance"],
        "owner_observed_at": (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).isoformat(),
    }
    job.discovery_metadata = meta
    await db_session.flush()
    await prepare(db_session, identity)
    row = await store.load(db_session, identity[0])
    assert row.value["state"] == "PAUSED" and row.value["packet_id"] is None
    assert row.value["diagnostic"] == "current_vacancy_requires_owner_review"


@pytest.mark.asyncio
async def test_profile_changes_block_resume_policy_and_old_revision(
    db_session, prepared_policy, phase2_profile
):
    await start(db_session)
    phase2_profile.summary = "Changed verified profile"
    await db_session.flush()
    await recurring.tick(db_session)
    view = await recurring.status(db_session)
    assert "confirmed_profile_version_required" in view["blockers"]
    assert await store.claim(db_session) is None
    with pytest.raises(ToolDenied, match="confirmed_profile_version"):
        await start(db_session)


@pytest.mark.asyncio
async def test_off_fences_and_stops_scheduler(db_session, prepared_policy):
    await imported(db_session)
    await start(db_session)
    await recurring.tick(db_session)
    identity = await store.claim(db_session)
    await store.configure(db_session, Configuration(mode="OFF"))
    assert (await recurring.record(db_session))["state"] == "STOPPED"
    with pytest.raises(ToolDenied):
        await store.fenced(db_session, identity)
    assert await store.claim(db_session) is None


@pytest.mark.asyncio
async def test_pause_revokes_browser_commands_and_plans(db_session, prepared_policy):
    job_id = await imported(db_session)
    await start(db_session)
    intent = (await store.start(db_session, [job_id]))[0]
    identity = await store.claim(db_session)
    await prepare(db_session, identity)
    row = await store.load(db_session, intent["id"])
    packet_id = row.value["packet_id"]
    # Only fields used by the production fence are needed for these synthetic
    # queued/leased commands. No native host or genuine profile is connected.
    for state in ["queued", "executing"]:
        db_session.add(
            OwnerPreference(
                key="chr_cmd:" + str(uuid4()),
                value={
                    "application_id": packet_id,
                    "state": state,
                    "version": 1,
                },
            )
        )
    db_session.add(
        OwnerPreference(
            key="fill_plan:" + str(uuid4()),
            value={
                "application_id": packet_id,
                "state": "authorized",
                "approved_fields": ["f0"],
            },
        )
    )
    current = await recurring.record(db_session)
    await recurring.control(
        db_session,
        AutomationControl(action="pause", expected_revision=current["revision"]),
    )
    commands = (
        await db_session.scalars(
            select(OwnerPreference).where(OwnerPreference.key.startswith("chr_cmd:"))
        )
    ).all()
    assert {c.value["state"] for c in commands} == {"cancelled", "outcome_unknown"}
    plans = (
        await db_session.scalars(
            select(OwnerPreference).where(OwnerPreference.key.startswith("fill_plan:"))
        )
    ).all()
    assert all(
        p.value["state"] == "read_only" and p.value["approved_fields"] == []
        for p in plans
    )


def test_unsupported_authority_cannot_be_saved():
    base = dict(
        profile_version=1,
        resume_resource_id=uuid4(),
        resume_version="a" * 64,
        allowed_roles=["Backend Developer"],
        allowed_locations=["India"],
        experience_min=0,
        experience_max=3,
    )
    for update in [
        {"permitted_actions": ["SUBMISSION"]},
        {"max_applications_per_day": 1},
        {"source": "private_api"},
        {"allowed_roles": [" "]},
        {"interval_seconds": 1},
    ]:
        with pytest.raises(ValidationError):
            AutomationPolicy(**{**base, **update})


@pytest.mark.asyncio
async def test_http_controls_persist_and_reject_stale_revision(
    async_client, phase2_auth, db_session, prepared_policy
):
    response = await async_client.post(
        "/api/v1/execution/naukri/automation/control",
        json={"action": "start", "expected_revision": 1},
        headers=phase2_auth,
    )
    assert response.status_code == 200 and response.json()["state"] == "RUNNING"
    response = await async_client.get("/api/v1/execution/naukri", headers=phase2_auth)
    assert response.json()["automation"]["state"] == "RUNNING"
    assert response.json()["automation"]["scope"] == "PARTIAL_PREPARATION"
    stopped = await async_client.post(
        "/api/v1/execution/naukri/automation/control",
        json={"action": "stop", "expected_revision": 2},
        headers=phase2_auth,
    )
    assert stopped.status_code == 200 and stopped.json()["revision"] == 3
    stale = await async_client.post(
        "/api/v1/execution/naukri/automation/control",
        json={"action": "start", "expected_revision": 2},
        headers=phase2_auth,
    )
    assert stale.status_code == 409
    unauthenticated = await async_client.post(
        "/api/v1/execution/naukri/automation/control",
        json={"action": "start", "expected_revision": 3},
    )
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_invalid_legacy_job_does_not_poison_scheduled_batch(
    db_session, prepared_policy
):
    db_session.add(
        Job(
            title="Malformed legacy fixture",
            source_platform="naukri",
            job_url="https://www.naukri.com/not-a-requisition",
        )
    )
    await imported(db_session)
    await start(db_session)
    await recurring.tick(db_session)
    view = await recurring.status(db_session)
    assert any(d["reason"] == "invalid_requisition_identity" for d in view["decisions"])
    assert len(await store.rows(db_session)) == 1


@pytest.mark.asyncio
async def test_policy_questions_queue_once_and_do_not_send(
    db_session, prepared_policy, monkeypatch
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.core.config import Settings
    from backend.app.execution import questions
    from backend.app.schemas.applications import QuestionInput, QuestionsAdd
    from backend.app.services.applications.service import ApplicationPacketService

    monkeypatch.setattr(
        "backend.app.core.config.get_settings",
        lambda: Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="fictional-bot-token",
            TELEGRAM_OWNER_USER_ID=123,
            TELEGRAM_OWNER_CHAT_ID=456,
        ),
    )
    policy = prepared_policy.model_copy(update={"telegram_questions": True})
    await recurring.configure(
        db_session, AutomationPolicyUpdate(expected_revision=1, policy=policy)
    )
    await imported(db_session)
    await start(db_session)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    identity = await ExecutionWorker(factory).tick()
    row = await store.load(db_session, identity[0])
    service = ApplicationPacketService(db_session)
    packet = await service.read(UUID(row.value["packet_id"]))
    await service.add_questions(
        packet.id,
        QuestionsAdd(
            expected_revision=packet.revision,
            questions=[
                QuestionInput(
                    question="What is your expected annual salary?",
                    required=True,
                    category="salary",
                )
            ],
        ),
    )
    await db_session.commit()
    await ExecutionWorker(factory).tick()
    await ExecutionWorker(factory).tick()
    rows = (
        await db_session.scalars(
            select(OwnerPreference).where(
                OwnerPreference.key.startswith(questions.PREFIX)
            )
        )
    ).all()
    salary = [
        r.value
        for r in rows
        if r.value["question"] == "What is your expected annual salary?"
    ]
    assert (
        len(salary) == 1
        and salary[0]["state"] == "pending"
        and salary[0]["message_ids"] == []
    )
    assert salary[0]["execution_id"] == identity[0]


@pytest.mark.asyncio
async def test_stop_fences_external_packet_questions_and_legacy_watch(
    db_session, prepared_policy, application_target
):
    from backend.app.execution.worker import watch
    from backend.app.schemas.applications import CreatePacket
    from backend.app.services.applications.service import ApplicationPacketService

    await start(db_session)
    job, _ = application_target
    job.source_platform = "naukri"
    job.job_url = "https://www.naukri.com/job-listings-fictional-external-281026123459"
    job.application_url = "https://jobs.lever.co/example/fictional-backend"
    await db_session.flush()
    packet = await ApplicationPacketService(db_session).create(
        job.id, CreatePacket(idempotency_key="external-question-stop")
    )
    intent = await store.packet_question_intent(db_session, packet)
    row = await store.load(db_session, intent["id"])
    row.value = {**row.value, "platform": "browser"}  # external employer packet
    current = await recurring.record(db_session)
    await recurring.control(
        db_session,
        AutomationControl(action="stop", expected_revision=current["revision"]),
    )
    assert (await store.load(db_session, intent["id"])).value["state"] == "PAUSED"
    with pytest.raises(ToolDenied, match="stopped"):
        await store.packet_question_intent(db_session, packet)
    await store.configure(db_session, Configuration(mode="WATCH_AND_NOTIFY"))
    assert await watch(db_session) == 0
