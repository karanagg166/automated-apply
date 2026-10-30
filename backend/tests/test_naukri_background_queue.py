"""Fictional native/queue/worker journeys; no installed Chrome or live submissions."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution.queue_contracts import (
    QueueControl,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.app.execution.queue_preparation import prepare_one, seed_saved_sources
from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.service import dispatch
from backend.app.models.job import Job
from backend.tests.test_application_queue import URL, running
from backend.tests.test_chrome_profiles import ACTOR, choose, connect, settings
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def call(session, context, name, work=None, **extra):
    fields = {"work_id": work["id"], "expected_work_revision": work["revision"],
              "work_lease_token": work["lease_token"], "tab_id": work["binding"]["tab_id"]} if work else {}
    return await dispatch(session, settings(), ACTOR, Command(command=name, **context, **(fields | extra)))


async def setup(session, *, browser_search=False):
    context = await connect(session)
    await choose(session, context)
    await running(session)
    if not browser_search:
        config = await queue.configuration(session)
        policy = QueuePolicy.model_validate(config["policy"])
        policy.platforms["naukri"].sources.remove("naukri_ui_search")
        value = await queue.configure(session, QueuePolicyUpdate(expected_revision=config["revision"], policy=policy))
        await queue.control(session, QueueControl(expected_revision=value["revision"], action="start"))
    return context


def job_report(req="291026123456", **changes):
    return {"kind": "job_facts", "observed_url": URL, "requisition": req,
            "job": {"requisition": req, "title": "Backend Developer", "company": "Fictional Labs",
                    "description": "Build Python backend services.", "location": "India", "skills": ["Python"],
                    "experience_min": 0, "experience_max": 3, "posted_at": datetime.now(timezone.utc).isoformat(),
                    "applicants_min": 4, "applicants_max": 4, "evidence_sha256": "a" * 64, **changes}}


async def observe(session, context, item):
    work = (await call(session, context, "poll_naukri_work")).data["work"]
    assert work and work["id"] == item["id"]
    bound = await call(session, context, "bind_naukri_work", work, tab_id=44)
    assert bound.ok, bound.error_code
    admitted = await call(session, context, "admit_naukri_work", bound.data["work"])
    assert admitted.ok, admitted.error_code
    return admitted.data["work"]


async def test_actual_native_fact_ingestion_and_worker_preparation_survive_fresh_sessions(db_session, upload_case):
    case = upload_case
    context = await setup(db_session)
    # This source is enabled independently of the UI-search producer.
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    result = await call(db_session, context, "finish_naukri_work", work, work_report=job_report())
    assert result.ok, result.error_code
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as worker, worker.begin():
        assert await prepare_one(worker, case.settings)
    async with factory() as dashboard:
        saved = (await queue.load(dashboard, item["id"])).value
        assert saved["stage"] == "READY_TO_APPLY", saved
        assert saved["packet_id"] and saved["match_score"] >= 80
        assert saved["upload_preflight"]["state"] == "PDF_VERIFIED_LOCAL"
        assert saved["status"] == "waiting" and saved["reason"] == "submission_executor_pending"
        assert not saved["admitted_actions"]
        job = await dashboard.get(Job, UUID(saved["job_id"]))
        assert job.discovery_metadata["data_provenance"]["method"] == "bound_browser_ui"
        assert await call(dashboard, context, "poll_naukri_work")


@pytest.mark.parametrize("changes,stage,reason", [
    ({"applicants_min": 10000, "applicants_max": None}, "SKIPPED", "applicant_limit_reached"),
    ({"applicants_min": None, "applicants_max": None}, "NEEDS_INPUT", "applicant_count_requires_review"),
    ({"posted_at": "2026-01-01T00:00:00Z"}, "SKIPPED", "posting_outside_age_limit"),
])
async def test_native_observations_enforce_saved_listing_filters(db_session, changes, stage, reason):
    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    result = await call(db_session, context, "finish_naukri_work", work, work_report=job_report(**changes))
    assert result.ok, result.error_code
    saved = (await queue.load(db_session, item["id"])).value
    assert (saved["stage"], saved["reason"]) == (stage, reason)
    assert saved["job_id"] is None


@pytest.mark.parametrize("change", ["session", "window", "tab", "secret", "identity", "revision"])
async def test_queue_native_cannot_observe_wrong_bound_context(db_session, change):
    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    fields = {"work_id": work["id"], "expected_work_revision": work["revision"], "work_lease_token": work["lease_token"], "tab_id": 44}
    actor = ACTOR
    if change == "session": context["browser_session_id"] = uuid4()
    if change == "window": context["window_id"] += 1
    if change == "tab": fields["tab_id"] += 1
    if change == "secret": context["profile_secret"] = "0" * 64
    if change == "identity": actor = Actor(channel="owner", identity="primary")
    if change == "revision": fields["expected_work_revision"] -= 1
    result = await dispatch(db_session, settings(), actor, Command(command="finish_naukri_work", **context, **fields, work_report=job_report()))
    assert not result.ok
    assert (await queue.load(db_session, item["id"])).value["job_id"] is None


async def test_stop_fences_native_response_and_legacy_preparation(db_session):
    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    await queue.put(db_session, "naukri_automation", {"state": "RUNNING", "revision": 4, "policy": None})
    config = await queue.configuration(db_session)
    await queue.control(db_session, QueueControl(action="stop", expected_revision=config["revision"]))
    finished = await call(db_session, context, "finish_naukri_work", work, work_report=job_report())
    assert not finished.ok and finished.error_code == "queue_lease_lost"
    assert (await db_session.get(OwnerPreference, "naukri_automation")).value["state"] == "STOPPED"


async def test_normal_ui_search_has_durable_poll_interval_and_same_queue_dedup(db_session, upload_case):
    context = await setup(db_session, browser_search=True)
    polled = await call(db_session, context, "poll_naukri_work")
    work = polled.data["work"]
    assert work["operation"] == "search_jobs" and work["url"] == "https://www.naukri.com/backend-developer-jobs"
    bound = await call(db_session, context, "bind_naukri_work", work, tab_id=44)
    admitted = await call(db_session, context, "admit_naukri_work", bound.data["work"])
    finished = await call(db_session, context, "finish_naukri_work", admitted.data["work"], work_report={
        "kind": "source_candidates", "observed_url": work["url"], "candidates": [URL, URL],
    })
    assert finished.ok, finished.error_code
    assert len(await queue.items(db_session)) == 1
    again = (await call(db_session, context, "poll_naukri_work")).data["work"]
    assert again["operation"] == "inspect_job"
    search = await db_session.get(OwnerPreference, "apply_search:naukri")
    assert search.value["next_at"] > search.value["last_started_at"]


async def test_saved_source_cursors_do_not_read_mail_or_enable_deferred_mailboxes(db_session):
    await running(db_session)
    for i, mailbox in enumerate(("local:1", "deferred:2")):
        db_session.add(OwnerPreference(key="nau_alert:" + str(uuid4()), value={
            "source": "gmail_job_alerts", "account_id": mailbox,
            "url": URL.replace("291026123456", str(291026123456 + i)),
        }))
    await db_session.commit()
    assert await seed_saved_sources(db_session) == 1
    await db_session.commit()
    assert await seed_saved_sources(db_session) == 0
    assert len(await queue.items(db_session)) == 1


async def test_owner_active_or_restart_blocks_only_one_job_and_never_queues_apply(db_session):
    context = await setup(db_session)
    first = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    second = await queue.enqueue(db_session, "naukri", URL.replace("291026123456", "291026654321"), "saved_verified_job")
    work = await observe(db_session, context, first)
    result = await call(db_session, context, "abandon_naukri_work", work,
        work_report={"kind": "needs_input", "reason": "owner_tab_active"})
    assert result.ok
    next_work = (await call(db_session, context, "poll_naukri_work")).data["work"]
    assert next_work["id"] == second["id"] and next_work["operation"] == "inspect_job"


async def test_platform_policy_revocation_fences_a_pending_native_observation(db_session):
    from backend.app.local_agent.contracts import PolicyUpdate
    from backend.app.local_agent.policies import get_policy, update_policy

    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    current = await get_policy(db_session)
    await update_policy(db_session, PolicyUpdate(expected_version=current["version"], default=current["default"],
        platforms={**current["platforms"], "naukri": "disabled"}))
    finished = await call(db_session, context, "finish_naukri_work", work, work_report=job_report())
    assert not finished.ok and finished.error_code == "platform_disabled"
    assert (await queue.load(db_session, item["id"])).value["job_id"] is None


async def test_disabling_a_source_excludes_old_messages_after_policy_restart(db_session):
    config = await running(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "approved_gmail_alerts")
    policy = QueuePolicy.model_validate(config["policy"])
    policy.platforms["naukri"].sources = ["saved_verified_job"]
    changed = await queue.configure(db_session, QueuePolicyUpdate(expected_revision=config["revision"], policy=policy))
    assert changed["state"] == "PAUSED"
    await queue.control(db_session, QueueControl(action="start", expected_revision=changed["revision"]))
    assert await queue.claim(db_session, "naukri", {"worker": "fictional"}) is None
    saved = (await queue.load(db_session, item["id"])).value
    assert saved["stage"] == "SKIPPED" and saved["reason"] == "queue_source_disabled"


async def test_dashboard_ledger_location_and_score_filters_use_persisted_values(db_session):
    await running(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "location": "Pune", "match_score": 85}
    await db_session.flush()
    assert (await queue.listing(db_session, location="pune", minimum_score=85))["total"] == 1
    assert (await queue.listing(db_session, location="Mumbai", minimum_score=80))["total"] == 0
    assert (await queue.listing(db_session, minimum_score=90))["total"] == 0


async def test_existing_global_execution_off_stops_new_queue_and_fences_native_work(db_session):
    from backend.app.agent.tools import ToolDenied
    from backend.app.execution import store
    from backend.app.execution.contracts import Configuration

    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    await store.configure(db_session, Configuration(mode="OFF"))
    stopped = await queue.configuration(db_session)
    assert stopped["state"] == "STOPPED"
    assert not (await call(db_session, context, "finish_naukri_work", work, work_report=job_report())).ok
    with pytest.raises(ToolDenied, match="execution_mode_off"):
        await queue.control(db_session, QueueControl(action="start", expected_revision=stopped["revision"]))
