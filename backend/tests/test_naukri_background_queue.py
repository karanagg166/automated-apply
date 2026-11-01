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
    import hashlib

    from sqlalchemy import select

    from backend.app.execution.naukri_identity import AccountApproval, approve
    from backend.app.models.candidate_profile import CandidateProfile

    candidate = await session.scalar(select(CandidateProfile).where(CandidateProfile.singleton_key == "primary"))
    if candidate:
        await approve(session, AccountApproval(expected_revision=0, candidate_profile_id=candidate.id,
            profile_binding_id=context["profile_binding_id"], account_sha256=hashlib.sha256(b"login-alias@example.org").hexdigest(),
            evidence_sha256="a" * 64, owner_confirmed=True))
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
        assert saved["status"] == "queued" and saved["operation"] == "inspect_profile"
        assert saved["reason"] is None
        assert not saved["admitted_actions"]
        job = await dashboard.get(Job, UUID(saved["job_id"]))
        assert job.discovery_metadata["data_provenance"]["method"] == "bound_browser_ui"
        assert await call(dashboard, context, "poll_naukri_work")


@pytest.mark.parametrize("change", [None, "running", "expired", "too_far", "binding", "nonce"])
async def test_extension_maintenance_requires_stopped_queue_current_binding_and_bounded_request(db_session, change):
    from datetime import timedelta

    from backend.app.browser import chrome_profiles as profiles
    from backend.app.execution.naukri_native import MAINTENANCE

    context = await setup(db_session)
    config = await queue.configuration(db_session)
    if change != "running":
        await queue.control(db_session, QueueControl(action="stop", expected_revision=config["revision"]))
    profile = await db_session.get(OwnerPreference, profiles.PROFILE + str(context["profile_binding_id"]))
    selection = await profiles.selection(db_session)
    binding = {"profile_binding_id": profile.value["id"], "profile_version": profile.value["version"],
               "selection_version": selection["version"], "browser_session_id": str(context["browser_session_id"]),
               "window_id": context["window_id"], "tab_id": None}
    seconds = -1 if change == "expired" else 180 if change == "too_far" else 60
    request = {"kind": "open_extension_manager", "request_id": str(uuid4()), "binding": binding,
               "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}
    if change == "binding":
        request["binding"] = {**binding, "window_id": 999}
    elif change == "nonce":
        request["request_id"] = 123
    await queue.put(db_session, MAINTENANCE, request)
    await db_session.commit()
    result = await call(db_session, context, "poll_naukri_work")
    assert result.ok, result.error_code
    assert bool(result.data.get("maintenance")) is (change is None)
    assert result.data["work"] is None and result.data["submitted"] is False


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


@pytest.mark.parametrize("previous_page, count, error, expected_page, expected_role", [
    (1, 0, None, 2, 0),
    (2, 0, None, 3, 0),
    (3, 0, None, 1, 1),
    (1, 4, None, 1, 1),
    (2, 0, "global_stop", 1, 1),
])
async def test_exhausted_search_pages_are_bounded_and_keep_interval_and_role_rotation(
    db_session, upload_case, previous_page, count, error, expected_page, expected_role,
):
    from datetime import timedelta

    from backend.app.automation.store import instant
    from backend.app.execution.naukri_native import SEARCH, search_work

    await setup(db_session, browser_search=True)
    roles = ["Backend Developer", "Frontend Developer"]
    config = await queue.configuration(db_session)
    policy = QueuePolicy.model_validate(config["policy"])
    policy.platforms["naukri"].preferences_mode = "custom"
    policy.platforms["naukri"].preferences.roles = roles
    now = await instant(db_session)
    old_url = "https://www.naukri.com/backend-developer-jobs"
    if previous_page > 1:
        old_url += "-" + str(previous_page)
    await queue.put(db_session, SEARCH, {
        "revision": 4, "status": "idle", "role_index": 1, "search_page": previous_page,
        "url": old_url, "last_cycle_count": count, "last_error": error,
        "last_finished_at": now.isoformat(), "next_at": (now - timedelta(seconds=1)).isoformat(),
        "candidates_found": 20,
    })
    binding = {"profile_binding_id": "fixture", "tab_id": None}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as restarted, restarted.begin():
        work = await search_work(restarted, config, policy, binding)
    slug = roles[expected_role].lower().replace(" ", "-")
    expected_url = "https://www.naukri.com/" + slug + "-jobs"
    if expected_page > 1:
        expected_url += "-" + str(expected_page)
    assert work["url"] == expected_url and work["search_page"] == expected_page
    assert work["role_index"] == expected_role + 1
    assert work["candidates_found"] == 20 and work["binding"] == binding
    assert datetime.fromisoformat(work["next_at"]) - datetime.fromisoformat(work["last_started_at"]) == timedelta(seconds=300)
    async with factory() as restarted, restarted.begin():
        assert await search_work(restarted, config, policy, binding) is None


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


@pytest.mark.parametrize("held", [None, "packet", "form", "admitted_action", "captcha"])
async def test_owner_platform_read_race_defers_without_replaying_writes(db_session, held):
    from datetime import timedelta

    from backend.app.automation.store import instant

    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    row = await queue.load(db_session, item["id"])
    value = dict(row.value)
    if held == "packet":
        value["packet_id"] = str(uuid4())
    elif held == "form":
        value["form_pending"] = True
    elif held == "admitted_action":
        value["admitted_actions"] = [{"fingerprint": "apply:initial"}]
    row.value = value
    reason = "provider_challenge_requires_owner" if held == "captcha" else "owner_platform_active"
    result = await call(db_session, context, "abandon_naukri_work", work,
                        work_report={"kind": "needs_input", "reason": reason})
    assert result.ok, result.error_code
    saved = dict((await queue.load(db_session, item["id"])).value)
    assert saved["operation"] == "inspect_job" and saved["lease_token"] is None
    assert saved["admitted_actions"] == value["admitted_actions"]
    if held:
        assert saved["stage"] == "NEEDS_INPUT" and saved["status"] == "waiting"
        assert (await call(db_session, context, "poll_naukri_work")).data["work"] is None
        return
    assert saved["stage"] == "FAILED_RETRYABLE" and saved["status"] == "queued"
    assert datetime.fromisoformat(saved["available_at"]) > await instant(db_session) + timedelta(seconds=50)
    assert (await call(db_session, context, "poll_naukri_work")).data["work"] is None
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "available_at": ((await instant(db_session)) - timedelta(seconds=1)).isoformat()}
    await db_session.commit()
    # A fresh process/session claims only another observation, never Apply.
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as restarted, restarted.begin():
        polled = await call(restarted, context, "poll_naukri_work")
        fresh = polled.data["work"]
        assert fresh["id"] == item["id"] and fresh["operation"] == "inspect_job"
        assert fresh["revision"] > work["revision"] and fresh["lease_token"] != work["lease_token"]


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


@pytest.mark.parametrize("day,now,reason", [
    ("2026-10-31", "2026-10-31T12:00:00+00:00", None),
    ("2026-10-30", "2026-10-31T12:00:00+00:00", "posting_age_requires_review"),
    ("2026-10-25", "2026-10-31T12:00:00+00:00", "posting_outside_age_limit"),
    ("2026-02-31", "2026-10-31T12:00:00+00:00", "posting_timestamp_unknown"),
])
def test_calendar_posting_date_enforces_worst_case_age_without_invented_time(day, now, reason):
    facts = {"posted_at": None, "posted_date": day, "applicants_min": 5, "applicants_max": 5}
    assert queue.listing_exclusion(facts, {"max_job_age_days": 2, "applicant_limit": 1000}, datetime.fromisoformat(now)) == reason


async def test_calendar_date_native_ingestion_preserves_unknown_exact_timestamp(db_session, upload_case):
    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    today = datetime.now(timezone.utc).date().isoformat()
    result = await call(db_session, context, "finish_naukri_work", work,
                        work_report=job_report(posted_at=None, posted_date=today))
    assert result.ok, result.error_code
    saved = (await queue.load(db_session, item["id"])).value
    assert saved["stage"] == "ELIGIBLE", saved
    job = await db_session.get(Job, UUID(saved["job_id"]))
    assert job.date_posted is None
    assert job.discovery_metadata["data_provenance"]["observed_posted_date"] == today


@pytest.mark.parametrize("changes,reason", [
    ({"experience_min": 5, "experience_max": 8}, "required_experience_outside_verified_band"),
    ({"skills": ["Rust"]}, "current_profile_preferences_or_required_skills_exclude_job"),
])
async def test_discovery_filters_before_scheduling_application_preparation(db_session, upload_case, changes, reason):
    from sqlalchemy import func, select

    from backend.app.models.application_packet import ApplicationPacket

    before = await db_session.scalar(select(func.count()).select_from(ApplicationPacket))
    context = await setup(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    work = await observe(db_session, context, item)
    finished = await call(db_session, context, "finish_naukri_work", work,
                          work_report=job_report(**changes))
    assert finished.ok, finished.error_code
    saved = (await queue.load(db_session, item["id"])).value
    assert saved["stage"] == "SKIPPED" and saved["reason"] == reason
    assert saved["operation"] == "inspect_job" and not saved["admitted_actions"]
    assert saved["facts"] and not saved.get("packet_id")
    assert not await prepare_one(db_session, upload_case.settings)
    assert await db_session.scalar(select(func.count()).select_from(ApplicationPacket)) == before


@pytest.mark.parametrize('status,stage,operation', [
    ('queued', 'DISCOVERED', 'inspect_job'),
    ('leased', 'DISCOVERED', 'inspect_job'),
    ('executing', 'DISCOVERED', 'inspect_job'),
    ('waiting', 'NEEDS_INPUT', 'inspect_job'),
    ('unknown', 'SUBMISSION_UNKNOWN', 'apply'),
])
async def test_idle_preparation_does_not_lock_owner_for_browser_work(db_session, monkeypatch, status, stage, operation):
    from datetime import timedelta

    from backend.app.execution import store

    await running(db_session)
    item = await queue.enqueue(db_session, 'naukri', URL, 'saved_verified_job')
    row = await queue.load(db_session, item['id'])
    row.value = {**row.value, 'status': status, 'stage': stage, 'operation': operation,
                 'lease_until': (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
                 if status in {'leased', 'executing'} else None}
    await db_session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail('Idle preparation must not compete for the owner lock')

    monkeypatch.setattr(store, 'memory_row', forbidden)
    assert await prepare_one(db_session, None) is False
    assert (await queue.load(db_session, item['id'])).value['status'] == status


async def test_preparation_fast_path_still_fences_expired_possible_apply(db_session):
    from datetime import timedelta

    await running(db_session)
    item = await queue.enqueue(db_session, 'naukri', URL, 'saved_verified_job')
    row = await queue.load(db_session, item['id'])
    row.value = {**row.value, 'status': 'executing', 'stage': 'APPLYING', 'operation': 'apply',
                 'lease_until': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    await db_session.commit()
    assert await prepare_one(db_session, None) is False
    saved = (await queue.load(db_session, item['id'])).value
    assert saved['stage'] == 'SUBMISSION_UNKNOWN' and saved['status'] == 'unknown'
    assert saved['operation'] == 'apply' and saved['lease_token'] is None
