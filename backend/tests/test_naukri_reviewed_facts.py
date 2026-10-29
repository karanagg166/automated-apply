"""Owner API to scheduler/claim/packet regressions; fictional records only."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.ai.schemas import GenerateRequest
from backend.app.execution import recurring, store
from backend.app.execution.contracts import AutomationPolicyUpdate, ImportJob
from backend.app.execution.naukri import normalize, reviewed_job_context
from backend.app.execution.naukri_review import review_jobs
from backend.app.execution.worker import ExecutionWorker, prepare
from backend.app.knowledge.reuse import job_digest
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.job_ingestion import JobIngestionService
from backend.tests.test_naukri_recurring import imported, start
from backend.tests.test_naukri_recurring import prepared_policy as prepared_policy


async def reimport(client, headers, url, **changes):
    now = datetime.now(timezone.utc).isoformat()
    response = await client.post(
        "/api/v1/execution/naukri/import",
        headers=headers,
        json={
            "jobs": [
                {
                    "url": url,
                    "title": "Backend Developer",
                    "employer": "Fictional Circuit",
                    "description": "Build Python backend APIs",
                    "location": "India",
                    "remote_type": "remote",
                    "employment_type": "full_time",
                    "required_skills": ["Python"],
                    "experience_min": 0,
                    "experience_max": 3,
                    "experience_requirement": "required",
                    "posting_status": "active",
                    "observed_at": now,
                    "posted_at": now,
                    **changes,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rejected_count"] == result["failed_count"] == 0, result
    assert len(result["job_ids"]) == 1


CHANGED_FACTS = [
    pytest.param({"title": "Backend Developer II"}, "role_outside_policy", id="title"),
    pytest.param({"employer": "Excluded Circuit"}, "excluded_company", id="employer"),
    pytest.param(
        {"required_skills": ["Rust"]}, "fit_requires_owner_review", id="skills"
    ),
    pytest.param(
        {"required_skills": []},
        "strict_skill_or_preference_match_required",
        id="skills-removed",
    ),
    pytest.param(
        {"experience_min": 3, "experience_max": 4},
        "required_experience_outside_verified_band",
        id="experience-band",
    ),
    pytest.param(
        {"experience_max": 4},
        "job_experience_band_outside_policy",
        id="policy-experience-band",
    ),
    pytest.param(
        {"experience_requirement": "preferred"},
        "required_experience_band_unknown",
        id="experience-preferred",
    ),
    pytest.param(
        {"experience_requirement": "unknown"},
        "required_experience_band_unknown",
        id="experience-unknown",
    ),
]


async def exclude_company(session, policy):
    policy = policy.model_copy(update={"excluded_companies": ["excluded circuit"]})
    await recurring.configure(
        session, AutomationPolicyUpdate(expected_revision=1, policy=policy)
    )
    return policy


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,reason", CHANGED_FACTS)
async def test_latest_owner_facts_cannot_queue_outside_policy(
    async_client, phase2_auth, db_session, prepared_policy, changes, reason
):
    await exclude_company(db_session, prepared_policy)
    identity = await imported(db_session)
    original = await db_session.get(Job, identity)
    url = original.job_url
    await db_session.commit()
    await reimport(async_client, phase2_auth, url, **changes)
    await start(db_session)
    await recurring.tick(db_session)
    assert await store.rows(db_session) == []
    decision = (await recurring.status(db_session))["decisions"][0]
    assert decision["reason"] == reason and not decision["eligible"]
    assert not await db_session.scalar(
        select(ApplicationPacket.id).where(ApplicationPacket.job_id == identity)
    )
    # The exact title reproduction must show the current reviewed title too.
    if "title" in changes:
        assert decision["title"] == changes["title"]
        assert original.title == "Backend Developer"
    if "employer" in changes:
        assert decision["employer"] == changes["employer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,reason", CHANGED_FACTS)
async def test_latest_owner_facts_rechecked_after_claim_and_on_resume(
    async_client, phase2_auth, db_session, prepared_policy, changes, reason
):
    await exclude_company(db_session, prepared_policy)
    job_id = await imported(db_session)
    cached_job = await db_session.get(Job, job_id)
    url = cached_job.job_url
    await start(db_session)
    await recurring.tick(db_session)
    claim = await store.claim(db_session)
    assert claim
    await db_session.commit()  # Real worker commits its claim before preparation.
    # A separate owner request changes facts while this session retains the old Job.
    await reimport(async_client, phase2_auth, url, **changes)
    await prepare(db_session, claim)
    execution = await store.load(db_session, claim[0])
    assert execution.value["state"] == "PAUSED"
    assert execution.value["diagnostic"] == reason
    assert execution.value["packet_id"] is None
    assert execution.value["lease_until"] is None
    assert not await db_session.scalar(
        select(ApplicationPacket.id).where(ApplicationPacket.job_id == job_id)
    )
    with pytest.raises(ToolDenied, match=reason):
        await store.control(db_session, claim[0], "resume", execution.value["revision"])
    assert await store.claim(db_session) is None


@pytest.mark.asyncio
async def test_accepted_corrections_use_same_facts_in_review_worker_and_packet(
    async_client, phase2_auth, db_session, prepared_policy
):
    policy = prepared_policy.model_copy(
        update={"allowed_roles": ["backend developer", "backend developer ii"]}
    )
    await recurring.configure(
        db_session, AutomationPolicyUpdate(expected_revision=1, policy=policy)
    )
    job_id = await imported(db_session)
    original = await db_session.get(Job, job_id)
    company = await db_session.get(Company, original.company_id)
    company.domain = "old-employer.example"
    company.metadata_ = {"startup_discovery": {"stage": "seed"}}
    original_company_id = company.id
    url = original.job_url
    await db_session.commit()
    await reimport(
        async_client,
        phase2_auth,
        url,
        title="Backend Developer II",
        employer="Reviewed Circuit",
        description="Current FastAPI requirements",
        required_skills=["Python", "FastAPI"],
    )
    await start(db_session)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, autoflush=False
    )
    claim = await ExecutionWorker(factory).tick()
    assert claim
    db_session.expire_all()
    execution = await store.load(db_session, claim[0])
    assert execution.value["state"] in {"READY_FOR_REVIEW", "NEEDS_INPUT"}
    packet = await ApplicationPacketService(db_session).read(
        UUID(execution.value["packet_id"])
    )
    assert not packet.readiness.stale
    assert packet.snapshot.job_title == "Backend Developer II"
    assert packet.snapshot.company_name == "Reviewed Circuit"
    assert packet.snapshot.company_id is None
    assert packet.snapshot.match.matched_skills == ["Python", "FastAPI"]
    original = await db_session.get(Job, job_id)
    assert (
        original.title == "Backend Developer"
        and original.company_id == original_company_id
    )
    assert original.skills_required == ["Python"]
    view, employer = reviewed_job_context(
        original, await db_session.get(Company, original_company_id)
    )
    assert view.description == "Current FastAPI requirements"
    assert (
        employer.name == "Reviewed Circuit"
        and employer.domain is None
        and employer.metadata_ == {}
    )
    decision = (await review_jobs(db_session, [original]))[0]
    assert decision["title"] == packet.snapshot.job_title
    assert decision["employer"] == packet.snapshot.company_name
    assert decision["match"] == packet.snapshot.match.model_dump()


@pytest.mark.asyncio
async def test_new_review_invalidates_prior_packet_without_reusing_old_facts(
    async_client, phase2_auth, db_session, prepared_policy
):
    job_id = await imported(db_session)
    job = await db_session.get(Job, job_id)
    url = job.job_url
    service = ApplicationPacketService(db_session)
    packet = await service.create(
        job_id, CreatePacket(idempotency_key="reviewed-facts-old-packet")
    )
    original_answer_context = await job_digest(db_session, job_id)
    await db_session.commit()
    await reimport(
        async_client,
        phase2_auth,
        url,
        employer="Reviewed Circuit",
        title="Backend Developer II",
        required_skills=["Rust"],
    )
    assert (await service.read(packet.id)).readiness.stale
    _, _, snapshot = await service.builder.context(job_id)
    assert snapshot.job_title == "Backend Developer II"
    assert snapshot.company_name == "Reviewed Circuit"
    assert snapshot.match.missing_skills == ["Rust"]
    assert await job_digest(db_session, job_id) != original_answer_context


@pytest.mark.asyncio
async def test_answers_use_reviewed_employer_and_description(
    async_client, phase2_auth, db_session, prepared_policy, phase2_settings
):
    job_id = await imported(db_session)
    job = await db_session.get(Job, job_id)
    url = job.job_url
    await db_session.commit()
    await reimport(
        async_client,
        phase2_auth,
        url,
        employer="Reviewed Circuit",
        description="Current FastAPI requirements",
    )
    db_session.expire_all()
    service = ApplicationAnswerService(db_session, phase2_settings)
    common = {"job_id": job_id, "question": "Email address"}
    rejected = await service.generate(
        GenerateRequest(**common, company_name="Fictional Circuit")
    )
    assert rejected.error_code == "company_context_mismatch"
    rejected = await service.generate(
        GenerateRequest(
            **common,
            company_name="Reviewed Circuit",
            job_description="Build Python backend APIs",
        )
    )
    assert rejected.error_code == "job_context_mismatch"
    current = await service.generate(
        GenerateRequest(
            **common,
            company_name="Reviewed Circuit",
            job_description="Current FastAPI requirements",
        )
    )
    assert current.answer == "alex@example.com" and not current.used_llm


@pytest.mark.asyncio
async def test_general_ingestion_cannot_silently_change_employer(
    db_session, prepared_policy
):
    job_id = await imported(db_session)
    job = await db_session.get(Job, job_id)
    item = normalize(
        ImportJob(url=job.job_url, title=job.title, employer="Unreviewed Circuit")
    )
    result = await JobIngestionService(db_session).ingest_jobs([item])
    assert result.rejected_count == 1 and not result.job_ids
    assert job.discovery_metadata["company_name"] == "Fictional Circuit"
