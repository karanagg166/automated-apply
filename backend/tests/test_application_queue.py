"""Durable PostgreSQL-compatible queue logic over isolated fictional SQLite data."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.queue_contracts import (
    PlatformQueuePolicy,
    QueueControl,
    QueueLimits,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.app.schemas.applications import CreatePacket
from backend.app.services.applications.service import ApplicationPacketService
from backend.tests.test_naukri_receipts import observation
from backend.tests.test_naukri_recurring import imported
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case

URL = "https://www.naukri.com/job-listings-fictional-291026123456"
BINDING = {"profile_binding_id": "fixture", "browser_session_id": "fixture-session", "window_id": 1, "tab_id": 2}


async def running(session, *, cap=80, mode="AUTOMATIC", authorized=True):
    policy = QueuePolicy(global_limits=QueueLimits(daily_cap=cap), platforms={"naukri": PlatformQueuePolicy(
        enabled=True, mode=mode, owner_submission_authorized=authorized,
    )})
    value = await queue.configure(session, QueuePolicyUpdate(expected_revision=0, policy=policy))
    return await queue.control(session, QueueControl(expected_revision=value["revision"], action="start"))


async def prepared_message(session, case, requisition):
    from backend.app.execution import naukri_identity as identity
    from backend.tests.test_chrome_profiles import choose, connect

    if not (await identity.status(session)).get("approved"):
        chrome = await connect(session)
        await choose(session, chrome)
        await identity.approve(session, identity.AccountApproval(expected_revision=0,
            candidate_profile_id=case.packet.candidate_profile_id, profile_binding_id=chrome["profile_binding_id"],
            account_sha256="a" * 64, evidence_sha256="b" * 64, owner_confirmed=True))
    account = await identity.require(session, case.packet.candidate_profile_id)
    job_id = await imported(session, requisition=requisition)
    await session.commit()
    packet = await ApplicationPacketService(session).create(job_id, CreatePacket(idempotency_key="queue-fixture-" + requisition))
    value = await queue.enqueue(session, "naukri", "https://www.naukri.com/job-listings-fictional-" + requisition, "naukri_ui_search")
    row = await queue.load(session, value["id"])
    now = datetime.now(timezone.utc).isoformat()
    row.value = {**row.value, "job_id": str(job_id), "packet_id": str(packet.id),
                 "candidate_profile_id": str(packet.candidate_profile_id), "account_sha256": account["account_sha256"],
                 "account_binding_revision": account["revision"],
                 "packet_revision": packet.revision, "profile_version": packet.candidate_profile_version,
                 "operation": "apply", "stage": "READY_TO_APPLY", "match_score": 90,
                 "facts": {"posted_at": now, "applicants_min": 4, "applicants_max": 4,
                           "prior_status": "NOT_APPLIED", "prior_status_checked_at": now,
                           "provider_resume_source": "profile_download_ui",
                           "provider_resume_checked_at": now, "provider_resume_sha256": case.private.sha256}}
    await session.commit()
    return row.value


def test_dashboard_defaults_are_owner_requested_bounded_values():
    policy = QueuePolicy()
    assert policy.global_limits.daily_cap == 80 and policy.global_limits.max_job_age_days == 2
    assert policy.global_limits.applicant_limit == 10000
    assert policy.background_only and policy.concurrency == 1
    assert not policy.platforms["naukri"].enabled
    assert not policy.platforms["naukri"].owner_submission_authorized
    with pytest.raises(ValidationError):
        QueueLimits(daily_cap=101)


def test_independent_global_and_platform_overrides():
    policy = QueuePolicy(platforms={"naukri": PlatformQueuePolicy(
        cap_mode="custom", age_mode="global", applicants_mode="custom",
        limits=QueueLimits(daily_cap=95, max_job_age_days=10, applicant_limit=250),
    )})
    effective = queue.limits(policy, "naukri")
    assert effective["daily_cap"] == 95 and effective["max_job_age_days"] == 2
    assert effective["applicant_limit"] == 250


@pytest.mark.parametrize("facts, reason", [
    ({"posted_at": "invalid"}, "posting_timestamp_unknown"),
    ({"posted_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}, "posting_outside_age_limit"),
    ({"applicants_min": 10000, "applicants_max": 10000}, "applicant_limit_reached"),
    ({"applicants_min": 10000, "applicants_max": None}, "applicant_limit_reached"),
    ({"applicants_min": 100, "applicants_max": None}, "applicant_count_requires_review"),
    ({"applicants_min": 0, "applicants_max": 99}, None),
    ({"applicants_min": 50, "applicants_max": 20}, "invalid_applicant_bounds"),
])
def test_age_and_applicant_bounds_never_invent_unknown_counts(facts, reason):
    now = datetime.now(timezone.utc)
    observed = {"posted_at": now.isoformat(), "applicants_min": 5, "applicants_max": 5, **facts}
    assert queue.listing_exclusion(observed, queue.limits(QueuePolicy(), "naukri"), now) == reason


async def test_messages_deduplicate_slugs_and_survive_restart(db_session):
    await running(db_session)
    first = await queue.enqueue(db_session, "naukri", URL, "approved_gmail_alerts", "private-fixture-reference")
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as restarted, restarted.begin():
        second = await queue.enqueue(restarted, "naukri", URL.replace("fictional", "changed-slug"), "naukri_ui_search")
        assert second["id"] == first["id"]
        assert len(await queue.items(restarted)) == 1
        claimed = await queue.claim(restarted, "naukri", BINDING)
        assert claimed["id"] == first["id"]
    public = await queue.listing(db_session)
    assert public["total"] == 1 and "lease_token" not in public["items"][0]
    assert "private-fixture-reference" not in str(public)


async def test_prior_receipt_is_permanently_excluded(db_session):
    db_session.add(OwnerPreference(key="naukri_receipt:291026123456", value={"uncertain": True}))
    await db_session.commit()
    with pytest.raises(ToolDenied, match="prior_receipt"):
        await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search")


async def test_retained_receipt_history_preserves_original_mode_and_never_creates_attempt(db_session):
    import copy

    source = observation()
    original = copy.deepcopy(source)
    db_session.add(OwnerPreference(key="naukri_receipt:291026123456", value=source))
    await db_session.commit()
    assert await queue.index_retained_receipts(db_session) == 1
    await db_session.commit()
    assert await queue.index_retained_receipts(db_session) == 0
    record = (await queue.listing(db_session))["items"][0]
    assert record["stage"] == "SUBMITTED_RECORDED" and record["attempts"] == 0
    assert record["submission_mode"] == "owner_authorized_software_operated_ui"
    assert (await db_session.get(OwnerPreference, "naukri_receipt:291026123456")).value == original
    assert (await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search"))["status"] == "complete"


async def test_pause_fences_old_claim_and_start_resumes_only_fresh_read(db_session):
    config = await running(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search")
    claimed = await queue.claim(db_session, "naukri", BINDING)
    paused = await queue.control(db_session, QueueControl(action="pause", expected_revision=config["revision"]))
    with pytest.raises(ToolDenied, match="queue_lease_lost"):
        await queue.admit(db_session, item["id"], claimed["revision"], claimed["lease_token"], BINDING)
    await queue.control(db_session, QueueControl(action="start", expected_revision=paused["revision"]))
    fresh = await queue.claim(db_session, "naukri", BINDING)
    assert fresh["operation"] == "inspect_job" and fresh["lease_token"] != claimed["lease_token"]


async def test_expired_write_is_unknown_and_not_redelivered(db_session):
    await running(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search")
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "operation": "apply", "status": "executing", "stage": "APPLYING",
                 "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    assert await queue.claim(db_session, "naukri", BINDING) is None
    assert (await queue.load(db_session, item["id"])).value["stage"] == "SUBMISSION_UNKNOWN"


async def test_daily_cap_is_reserved_transactionally_and_waiting_jobs_are_independent(db_session, upload_case):
    case = upload_case
    await running(db_session, cap=2)
    ids = []
    for req in ["291026111111", "291026222222", "291026333333"]:
        ids.append((await prepared_message(db_session, case, req))["id"])
    from backend.app.execution.naukri_identity import require
    binding = {**BINDING, "profile_binding_id": (await require(db_session))["profile_binding_id"]}
    for identity in ids[:2]:
        claimed = await queue.claim(db_session, "naukri", binding)
        assert claimed["id"] == identity
        admitted = await queue.admit(db_session, identity, claimed["revision"], claimed["lease_token"], binding, case.settings)
        row = await queue.load(db_session, identity)
        row.value = {**admitted, "stage": "NEEDS_INPUT", "status": "waiting", "lease_until": None, "lease_token": None}
        await db_session.commit()
    third = await queue.claim(db_session, "naukri", binding)
    with pytest.raises(ToolDenied, match="daily_application_cap_reached"):
        await queue.admit(db_session, third["id"], third["revision"], third["lease_token"], binding, case.settings)


async def test_local_pdf_without_provider_resume_proof_cannot_admit_apply(db_session, upload_case):
    case = upload_case
    await running(db_session)
    message = await prepared_message(db_session, case, "291026111111")
    row = await queue.load(db_session, message["id"])
    row.value = {**row.value, "facts": {**row.value["facts"], "provider_resume_sha256": "0" * 64}}
    from backend.app.execution.naukri_identity import require
    binding = {**BINDING, "profile_binding_id": (await require(db_session))["profile_binding_id"]}
    claimed = await queue.claim(db_session, "naukri", binding)
    with pytest.raises(ToolDenied, match="fresh_provider_resume_binding_required"):
        await queue.admit(db_session, claimed["id"], claimed["revision"], claimed["lease_token"], binding, case.settings)


async def test_dashboard_queue_api_owner_policy_and_filters(async_client, phase2_auth, db_session):
    response = await async_client.get("/api/v1/execution/queue", headers=phase2_auth)
    assert response.status_code == 200 and response.json()["configuration"]["state"] == "STOPPED"
    policy = QueuePolicy(platforms={"naukri": PlatformQueuePolicy(enabled=True)})
    updated = await async_client.put("/api/v1/execution/queue/policy", headers=phase2_auth,
        json={"expected_revision": 0, "policy": policy.model_dump(mode="json")})
    assert updated.status_code == 200
    started = await async_client.post("/api/v1/execution/queue/control", headers=phase2_auth,
        json={"expected_revision": updated.json()["revision"], "action": "start"})
    assert started.status_code == 200
    await queue.enqueue(db_session, "naukri", URL, "naukri_ui_search")
    await db_session.commit()
    filtered = await async_client.get("/api/v1/execution/queue?stage=DISCOVERED&search=291026123456", headers=phase2_auth)
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    assert (await async_client.get("/api/v1/execution/queue?stage=SUBMITTED_RECORDED", headers=phase2_auth)).json()["total"] == 0
    denied = await async_client.put("/api/v1/execution/queue/policy", headers={**phase2_auth, "X-Agent-Client": "fixture-extension"},
        json={"expected_revision": 0, "policy": policy.model_dump(mode="json")})
    assert denied.status_code == 403
