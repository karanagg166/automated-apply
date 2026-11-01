"""Fictional owner filter changes; never a provider visit, Apply or receipt."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    OwnerPreference,
)
from backend.app.execution import application_queue as queue
from backend.app.execution import queue_reconsideration as rechecks
from backend.app.execution.queue_contracts import (
    QueueControl,
    QueueLimits,
    QueuePolicy,
    QueuePolicyUpdate,
)
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.tests.test_application_queue import URL
from backend.tests.test_naukri_background_queue import job_report, setup
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


@pytest.mark.parametrize("lower,upper,expected", [
    (100, None, None), (None, None, "applicant_count_requires_review"),
    (1000, None, "applicant_limit_reached"), (999, None, None),
    (999, 1500, "applicant_count_requires_review"), (0, 999, None),
    (-1, None, "invalid_applicant_bounds"), (100, 50, "invalid_applicant_bounds"),
])
def test_lower_bound_exception_never_invents_a_count_or_allows_totally_missing_counts(lower, upper, expected):
    now = datetime.now(timezone.utc)
    limits = QueueLimits(applicant_limit=1000, unknown_applicants="allow_lower_bound").model_dump()
    facts = {"posted_at": now.isoformat(), "applicants_min": lower, "applicants_max": upper}
    assert queue.listing_exclusion(facts, limits, now) == expected
    if lower == 100 and upper is None:
        assert queue.listing_exclusion(facts, {**limits, "unknown_applicants": "needs_review"}, now) == "applicant_count_requires_review"


async def held(session, url=URL):
    item = await queue.enqueue(session, "naukri", url, "saved_verified_job")
    row = await queue.load(session, item["id"])
    row.value = {**row.value, "stage": "NEEDS_INPUT", "status": "waiting",
                 "reason": "applicant_count_requires_review",
                 "facts": job_report(req=url.rsplit("-", 1)[-1], applicants_min=100, applicants_max=None)["job"]}
    await session.flush()
    return row


async def allow_lower_bounds(session):
    current = await queue.configuration(session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.global_limits.applicant_limit = 1000
    policy.global_limits.unknown_applicants = "allow_lower_bound"
    configured = await queue.configure(session, QueuePolicyUpdate(expected_revision=current["revision"], policy=policy))
    return await queue.control(session, QueueControl(action="start", expected_revision=configured["revision"]))


async def test_policy_answer_schedules_fresh_read_of_same_identity_before_preparation(db_session, upload_case):
    await setup(db_session)
    row = await held(db_session)
    identity = row.value["id"]
    await allow_lower_bounds(db_session)
    assert await rechecks.tick(db_session)
    value = (await queue.load(db_session, identity)).value
    assert value["stage"] == "DISCOVERED" and value["operation"] == "inspect_job"
    assert value["status"] == "queued" and value["binding"] is None
    assert value["profile_version"] is None and value["last_filter_recheck"]["retained_facts_only"]
    assert not value.get("packet_id") and not value["admitted_actions"]
    assert not await rechecks.tick(db_session)
    assert (await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)).value["status"] == "complete"
    assert (await queue.enqueue(db_session, "naukri", URL.replace("fictional", "another-slug"), "saved_verified_job"))["id"] == identity
    assert len(await queue.items(db_session)) == 1


@pytest.mark.parametrize("protected", ["action", "packet", "form", "lease", "receipt", "worker_receipt", "terminal_packet", "applied_job"])
async def test_filter_change_never_reopens_packet_historical_or_uncertain_work(db_session, upload_case, protected):
    from uuid import UUID

    from backend.app.models.application_packet import ApplicationPacket
    from backend.app.models.job import Job
    from backend.app.schemas.applications import CreatePacket
    from backend.app.services.applications.service import ApplicationPacketService
    from backend.tests.test_naukri_recurring import imported

    await setup(db_session)
    row = await held(db_session)
    value = dict(row.value)
    if protected == "action":
        value["admitted_actions"] = [{"fingerprint": "apply:initial"}]
    elif protected == "packet":
        value["packet_id"] = str(upload_case.packet.id)
    elif protected == "form":
        value["form_pending"] = True
    elif protected == "lease":
        value["lease_until"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif protected in {"receipt", "worker_receipt"}:
        prefix = "naukri_receipt:" if protected == "receipt" else "naukri_worker_receipt:"
        db_session.add(OwnerPreference(key=prefix + value["requisition"], value={"uncertain": True}))
    else:
        job_id = await imported(db_session, requisition=value["requisition"])
        job = await db_session.get(Job, UUID(str(job_id)))
        if protected == "applied_job":
            job.status = "applied"
        else:
            packet = await ApplicationPacketService(db_session).create(job.id, CreatePacket(idempotency_key="fictional-uncertain-recheck"))
            stored = await db_session.get(ApplicationPacket, packet.id)
            stored.lifecycle_state = "submission_unknown"
    row.value = value
    if protected == "lease":
        await rechecks.request(db_session, "fixture_profile_changed_with_live_read")
    else:
        await allow_lower_bounds(db_session)
    before = dict((await queue.load(db_session, value["id"])).value)
    assert not await rechecks.tick(db_session)
    assert (await queue.load(db_session, value["id"])).value == before


async def test_only_filter_or_new_confirmed_profile_changes_request_reconsideration(db_session, upload_case):
    await setup(db_session)
    marker = await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)
    marker.value = {**marker.value, "status": "complete"}
    original_id = marker.value["id"]
    await db_session.flush()
    from backend.app.execution.recurring import context

    profile, _, _ = await context(db_session)
    await confirm_profile(db_session, profile, profile.version)
    current = await queue.configuration(db_session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.global_limits.daily_cap += 1
    await queue.configure(db_session, QueuePolicyUpdate(expected_revision=current["revision"], policy=policy))
    assert (await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)).value["id"] == original_id
    profile.version += 1
    await db_session.flush()
    await confirm_profile(db_session, profile, profile.version)
    marker = await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)
    assert marker.value["id"] != original_id and marker.value["status"] == "pending"


async def test_applicant_policy_question_is_one_in_app_question_until_explicit_answer(db_session):
    from sqlalchemy import select

    await setup(db_session)
    policy = QueuePolicy.model_validate((await queue.configuration(db_session))["policy"])
    await rechecks.notify_applicant_review(db_session, policy)
    await rechecks.notify_applicant_review(db_session, policy)
    notice = (await db_session.scalars(select(Notification))).one()
    assert notice.kind == "automation_policy_question" and notice.href == "/naukri"
    assert len((await db_session.scalars(select(NotificationDelivery))).all()) == 1
    answer = policy.model_copy(deep=True)
    answer.global_limits.unknown_applicants = "allow_lower_bound"
    await rechecks.resolve_applicant_review(db_session, policy, answer)
    await db_session.refresh(notice)
    assert notice.kind == "automation_policy_resolved" and notice.read_at is None


async def test_reconsideration_uses_bounded_batches_and_durable_cursor(db_session, upload_case):
    await setup(db_session)
    for index in range(rechecks.BATCH + 2):
        await held(db_session, URL.rsplit("-", 1)[0] + "-" + str(291026230000 + index))
    await allow_lower_bounds(db_session)
    assert await rechecks.tick(db_session)
    values = [row.value for row in await queue.items(db_session)]
    assert sum(v["stage"] == "DISCOVERED" for v in values) == rechecks.BATCH
    marker = await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)
    assert marker.value["fresh_reads"] == rechecks.BATCH and marker.value["cursor"]
    assert await rechecks.tick(db_session)
    assert not await rechecks.tick(db_session)
    marker = await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)
    assert marker.value["status"] == "complete" and marker.value["fresh_reads"] == rechecks.BATCH + 2
    assert len(await queue.items(db_session)) == rechecks.BATCH + 2


async def test_backpressure_preserves_cursor_and_idle_backoff_avoids_owner_lock(db_session, upload_case, monkeypatch):
    await setup(db_session)
    target = await held(db_session)
    target.value = {**target.value, "stage": "SKIPPED", "status": "complete", "reason": "applicant_limit_reached"}
    blocker = await queue.enqueue(db_session, "naukri", URL.rsplit("-", 1)[0] + "-291026987654", "saved_verified_job")
    current = await queue.configuration(db_session)
    policy = QueuePolicy.model_validate(current["policy"])
    policy.max_pending = 1
    policy.global_limits.applicant_limit = 1000
    policy.global_limits.unknown_applicants = "allow_lower_bound"
    configured = await queue.configure(db_session, QueuePolicyUpdate(expected_revision=current["revision"], policy=policy))
    await queue.control(db_session, QueueControl(action="start", expected_revision=configured["revision"]))
    assert not await rechecks.tick(db_session)
    marker = await db_session.get(OwnerPreference, rechecks.KEY, populate_existing=True)
    assert marker.value["cursor"] is None and marker.value["retry_after"]
    assert (await queue.load(db_session, target.value["id"])).value["stage"] == "SKIPPED"
    from backend.app.execution import store

    original_lock = store.memory_row
    async def forbidden_lock(*args, **kwargs):
        raise AssertionError("backed-off recheck took owner lock")
    monkeypatch.setattr(store, "memory_row", forbidden_lock)
    assert not await rechecks.tick(db_session)
    monkeypatch.setattr(store, "memory_row", original_lock)
    other = await queue.load(db_session, blocker["id"])
    other.value = {**other.value, "stage": "SKIPPED", "status": "complete", "reason": "fictional_nonfilter_exclusion"}
    marker.value = {**marker.value, "retry_after": None}
    await db_session.flush()
    assert await rechecks.tick(db_session)
    assert (await queue.load(db_session, target.value["id"])).value["stage"] == "DISCOVERED"


@pytest.mark.parametrize("changed", ["stop", "profile", "request", "action", "receipt"])
async def test_preloaded_decisions_are_revalidated_inside_owner_fence(db_session, upload_case, monkeypatch, changed):
    from backend.app.execution import store
    from backend.app.execution.recurring import context

    await setup(db_session)
    row = await held(db_session)
    await allow_lower_bounds(db_session)
    original_lock = store.memory_row

    async def change_before_fence(*args, **kwargs):
        owner = await original_lock(*args, **kwargs)
        if changed == "stop":
            current = await queue.configuration(db_session)
            await queue.put(db_session, queue.POLICY_KEY, {**current, "state": "STOPPED", "revision": current["revision"] + 1})
        elif changed == "profile":
            profile, _, _ = await context(db_session)
            profile.version += 1
        elif changed == "request":
            await rechecks.request(db_session, "newer_owner_request")
        elif changed == "action":
            row.value = {**row.value, "revision": row.value["revision"] + 1,
                         "admitted_actions": [{"fingerprint": "fictional-uncertain-action"}]}
        else:
            db_session.add(OwnerPreference(key="naukri_receipt:" + row.value["requisition"], value={"uncertain": True}))
        await db_session.flush()
        return owner

    monkeypatch.setattr(store, "memory_row", change_before_fence)
    assert not await rechecks.tick(db_session)
    assert (await queue.load(db_session, row.value["id"])).value["stage"] == "NEEDS_INPUT"
