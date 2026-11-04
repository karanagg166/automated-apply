"""Fictional persisted native-to-worker journeys; no employer/network actions."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import Notification, OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_submission as submission
from backend.app.execution.naukri_receipts import prevents_replay
from backend.app.execution.queue_contracts import QueueControl
from backend.app.execution.queue_preparation import prepare_one
from backend.app.local_agent.contracts import Command
from backend.app.local_agent.service import dispatch
from backend.app.models.application_packet import (
    ApplicationPacket,
    ApplicationSubmissionEvidence,
)
from backend.app.models.job import Job
from backend.tests.test_application_queue import URL, prepared_message, running
from backend.tests.test_chrome_profiles import ACTOR, settings
from backend.tests.test_naukri_background_queue import job_report, setup
from backend.tests.test_naukri_upload_preflight import upload_case as upload_case


async def call(session, case, context, name, work=None, **extra):
    fields = {"work_id": work["id"], "expected_work_revision": work["revision"],
              "work_lease_token": work["lease_token"], "tab_id": work["binding"]["tab_id"]} if work else {}
    config = settings().model_copy(update={"RESUME_ENCRYPTION_KEY": case.settings.RESUME_ENCRYPTION_KEY})
    result = await dispatch(session, config, ACTOR, Command(command=name, **context, **(fields | extra)))
    await session.commit()  # The external browser would run AFTER this commit.
    return result


async def claim(session, case, context):
    result = await call(session, case, context, "poll_naukri_work")
    assert result.ok, result.error_code
    work = result.data["work"]
    if work:
        bound = await call(session, case, context, "bind_naukri_work", work, tab_id=44)
        assert bound.ok, bound.error_code
        return bound.data["work"]


async def admit(session, case, context, work):
    result = await call(session, case, context, "admit_naukri_work", work)
    assert result.ok, result.error_code
    return result.data["work"]


def observation(work, state, **changes):
    return {"kind": "execution_observation", "observed_url": work["target_url"], "requisition": work["requisition"],
            "execution": {"state": state, "document_id": str(uuid4()), "evidence_sha256": "a" * 64,
                          "account_sha256": work["execution"]["expected_account_sha256"], **changes}}


async def finish(session, case, context, work, report):
    result = await call(session, case, context, "finish_naukri_work", work, work_report=report)
    assert result.ok, result.error_code
    return result.data["work"]


async def ready(session, case):
    context = await setup(session)
    item = await queue.enqueue(session, "naukri", URL, "saved_verified_job")
    work = await admit(session, case, context, await claim(session, case, context))
    report = job_report()
    await finish(session, case, context, work, report)
    assert await prepare_one(session, case.settings)
    await session.commit()
    return context, item, report


async def apply_ready(session, case):
    context, item, facts = await ready(session, case)
    work = await admit(session, case, context, await claim(session, case, context))
    assert work["operation"] == "inspect_profile"
    report = observation(work, "PROFILE_VERIFIED", resume_sha256=case.private.sha256, resume_bytes=len(case.raw))
    work = await finish(session, case, context, work, report)
    assert work["operation"] == "inspect_application"
    work = await admit(session, case, context, work)
    report = observation(work, "NOT_APPLIED", title="Backend Developer", company="Fictional Labs", control_sha256="b" * 64)
    report["job"] = facts["job"]
    work = await finish(session, case, context, work, report)
    assert work["operation"] == "apply"
    return context, item, work


async def history_ready(session, case, context):
    work = await admit(session, case, context, await claim(session, case, context))
    assert work["operation"] == "verify_account"
    assert work["target_url"] == submission.PROFILE_URL
    work = await finish(session, case, context, work, observation(work, "PROFILE_OBSERVED"))
    assert work["operation"] == "reconcile_application"
    assert work["execution"]["account_observation"]["source"] == "profile_ui"
    return await admit(session, case, context, work)


async def test_complete_native_worker_direct_apply_and_two_independent_receipts(db_session, upload_case):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    work = await admit(db_session, case, context, work)
    saved = (await queue.load(db_session, item["id"])).value
    packet = await db_session.get(ApplicationPacket, UUID(saved["packet_id"]))
    assert packet.lifecycle_state == "submitting"  # Fences all legacy channels before clicking.
    assert work["execution"]["permit_expires_at"]
    report = observation(work, "CLICKED", document_id=work["execution"]["document_id"])
    await finish(db_session, case, context, work, report)
    assert (await queue.load(db_session, item["id"])).value["stage"] == "VERIFYING"
    assert not await prevents_replay(db_session, item["requisition"])  # No false receipt on click.
    first = await history_ready(db_session, case, context)
    report = observation(first, "APPLICATION_SENT", title="Backend Developer", company="Fictional Labs")
    await finish(db_session, case, context, first, report)
    assert (await queue.load(db_session, item["id"])).value["stage"] == "VERIFYING"
    second = await history_ready(db_session, case, context)
    report = observation(second, "APPLICATION_SENT", title="Backend Developer", company="Fictional Labs")
    await finish(db_session, case, context, second, report)
    saved = (await queue.load(db_session, item["id"])).value
    assert saved["stage"] == "SUBMITTED_CONFIRMED"
    assert len(saved["admitted_actions"]) == 1
    assert await prevents_replay(db_session, item["requisition"])
    packet = await db_session.get(ApplicationPacket, UUID(saved["packet_id"]), populate_existing=True)
    assert packet.lifecycle_state == "provider_confirmed_submitted"
    evidence = await db_session.scalar(select(ApplicationSubmissionEvidence).where(ApplicationSubmissionEvidence.packet_id == packet.id))
    assert evidence.human_confirmed is False and evidence.evidence_confidence == "provider_ui_persistent"
    job = await db_session.get(Job, UUID(saved["job_id"]))
    assert job.status == "applied"
    assert len((await db_session.scalars(select(Notification).where(Notification.kind == "application_submitted"))).all()) == 1
    assert await claim(db_session, case, context) is None


@pytest.mark.parametrize("change,code", [("resume", "provider_saved_resume_differs_from_canonical_pdf"), ("account", "provider_account_identity_changed")])
async def test_wrong_provider_resume_or_account_cannot_schedule_apply(db_session, upload_case, change, code):
    case = upload_case
    context, item, _ = await ready(db_session, case)
    work = await admit(db_session, case, context, await claim(db_session, case, context))
    report = observation(work, "PROFILE_VERIFIED", resume_sha256=case.private.sha256, resume_bytes=len(case.raw))
    report["execution"]["resume_sha256" if change == "resume" else "account_sha256"] = "0" * 64
    result = await call(db_session, case, context, "finish_naukri_work", work, work_report=report)
    assert not result.ok and result.error_code == code
    assert not (await queue.load(db_session, item["id"])).value["admitted_actions"]


async def test_lost_apply_result_reconciles_only_and_never_replays(db_session, upload_case):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    work = await admit(db_session, case, context, work)
    result = await call(db_session, case, context, "abandon_naukri_work", work,
                        work_report={"kind": "failed", "reason": "backend_timeout"})
    assert result.ok
    saved = (await queue.load(db_session, item["id"])).value
    assert saved["stage"] == "SUBMISSION_UNKNOWN" and saved["status"] == "unknown"
    assert await claim(db_session, case, context) is None  # Persistent cooldown.
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "available_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    await db_session.commit()
    retry = await claim(db_session, case, context)
    assert retry["operation"] == "verify_account"
    assert len((await queue.load(db_session, item["id"])).value["admitted_actions"]) == 1


async def test_stop_after_snapshot_fences_apply_without_reservation(db_session, upload_case):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    current = await queue.configuration(db_session)
    await queue.control(db_session, QueueControl(action="stop", expected_revision=current["revision"]))
    await db_session.commit()
    result = await call(db_session, case, context, "admit_naukri_work", work)
    assert not result.ok
    assert not (await queue.load(db_session, item["id"])).value["admitted_actions"]


@pytest.mark.parametrize("change", ["expired", "future", "binding", "work", "source", "document"])
async def test_apply_requires_fresh_account_observation_from_same_profile_document_context(db_session, upload_case, change):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    row = await queue.load(db_session, item["id"])
    proof = dict(row.value["account_observation"])
    if change == "expired":
        proof["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    elif change == "future":
        proof["observed_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif change == "binding":
        proof["binding"] = {**proof["binding"], "tab_id": 999}
    elif change == "work":
        proof["work_id"] = str(uuid4())
    elif change == "document":
        proof["profile_document_id"] = "bad"
    else:
        proof["source"] = "candidate_contact_email"
    row.value = {**row.value, "account_observation": proof}
    await db_session.commit()
    result = await call(db_session, case, context, "admit_naukri_work", work)
    assert not result.ok and result.error_code == "fresh_provider_account_observation_required"
    assert not (await queue.load(db_session, item["id"])).value["admitted_actions"]


async def test_history_account_refresh_cannot_be_replaced_with_a_receipt_or_wrong_account(db_session, upload_case):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    work = await admit(db_session, case, context, work)
    await finish(db_session, case, context, work, observation(work, "CLICKED", document_id=work["execution"]["document_id"]))
    check = await admit(db_session, case, context, await claim(db_session, case, context))
    assert check["operation"] == "verify_account"
    result = await call(db_session, case, context, "finish_naukri_work", check,
                        work_report=observation(check, "APPLICATION_SENT", title="Backend Developer", company="Fictional Labs"))
    assert not result.ok and result.error_code == "provider_account_profile_observation_required"
    result = await call(db_session, case, context, "finish_naukri_work", check,
                        work_report=observation(check, "PROFILE_OBSERVED", account_sha256="0" * 64))
    assert not result.ok and result.error_code == "provider_account_identity_changed"
    assert len((await queue.load(db_session, item["id"])).value["admitted_actions"]) == 1
    assert not await prevents_replay(db_session, item["requisition"])  # No receipt manufactured.


async def test_repeated_history_account_failures_are_bounded_without_replaying_apply(db_session, upload_case):
    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    work = await admit(db_session, case, context, work)
    await finish(db_session, case, context, work, {"kind": "failed", "reason": "browser_result_lost"})
    for attempt in range(3):
        assert await claim(db_session, case, context) is None  # Persisted history cooldown.
        row = await queue.load(db_session, item["id"])
        row.value = {**row.value, "available_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
        await db_session.commit()
        check = await admit(db_session, case, context, await claim(db_session, case, context))
        assert check["operation"] == "verify_account"
        await finish(db_session, case, context, check, {"kind": "needs_input", "reason": "provider_account_identity_unverified"})
        saved = (await queue.load(db_session, item["id"])).value
        assert saved["account_recheck_attempts"] == attempt + 1
        assert saved["status"] == "unknown" and len(saved["admitted_actions"]) == 1
    assert await claim(db_session, case, context) is None
    assert (await queue.load(db_session, item["id"])).value["status"] == "unknown"


async def test_hourly_reservation_limit_is_independent_of_daily_cap(db_session, upload_case):
    case = upload_case
    await running(db_session, cap=80, hourly_cap=2)
    binding = {"worker": "fictional"}
    for i in range(2):
        item = await prepared_message(db_session, case, str(291026110000 + i), binding=binding)
        row = await queue.load(db_session, item["id"])
        row.value = {**row.value, "status": "waiting", "stage": "SUBMISSION_UNKNOWN", "admitted_actions": [
            {"id": str(uuid4()), "fingerprint": "apply:initial", "at": datetime.now(timezone.utc).isoformat()}]}
    await prepared_message(db_session, case, "291026119999", binding=binding)
    work = await queue.claim(db_session, "naukri", binding)
    with pytest.raises(ToolDenied, match="hourly_application_cap_reached"):
        await queue.admit(db_session, work["id"], work["revision"], work["lease_token"], binding, case.settings)


async def test_existing_worker_receipt_fences_all_future_slug_variants(db_session):
    await running(db_session)
    db_session.add(OwnerPreference(key=submission.RECEIPT_PREFIX + "291026123456", value={"damaged": True}))
    with pytest.raises(ToolDenied, match="prior_receipt"):
        await queue.enqueue(db_session, "naukri", URL.replace("fictional", "another-slug"), "saved_verified_job")


async def test_authenticated_popup_can_stop_queue_but_cannot_change_policy(db_session, upload_case):
    case = upload_case
    context, _, _ = await ready(db_session, case)
    status = await call(db_session, case, context, "naukri_queue_status")
    assert status.ok and status.data["queue"]["state"] == "RUNNING"
    revision = status.data["queue"]["revision"]
    stopped = await call(db_session, case, context, "naukri_queue_control", queue_action="stop", expected_queue_revision=revision)
    assert stopped.ok and stopped.data["queue"]["state"] == "STOPPED"
    repeat = await call(db_session, case, context, "naukri_queue_control", queue_action="start", expected_queue_revision=revision)
    assert not repeat.ok and repeat.error_code == "queue_policy_revision_conflict"


@pytest.mark.parametrize("minimum_match_score", [50, 80])
async def test_telegram_job_url_uses_same_queue_and_pause_fence(db_session, minimum_match_score):
    from backend.app.execution.telegram_commands import command

    await running(db_session, minimum_match_score=minimum_match_score)
    response = await command(db_session, "/naukri add " + URL)
    assert "DISCOVERED" in response
    assert "PAUSED" in await command(db_session, "/naukri queue pause")
    assert (await queue.configuration(db_session))["state"] == "PAUSED"
    assert "RUNNING" in await command(db_session, "/naukri queue resume")
    assert len(await queue.items(db_session)) == 1


@pytest.mark.parametrize("revocation", ["expiry", "pause"])
async def test_unadmitted_apply_recovers_with_fresh_profile_proof(db_session, revocation):
    current = await running(db_session)
    item = await queue.enqueue(db_session, "naukri", URL, "saved_verified_job")
    await queue.claim(db_session, "naukri", {"worker": "fictional"})
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "operation": "apply", "stage": "READY_TO_APPLY", "account_sha256": "a" * 64}
    if revocation == "expiry":
        row.value = {**row.value, "lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    else:
        paused = await queue.control(db_session, QueueControl(action="pause", expected_revision=current["revision"]))
        await queue.control(db_session, QueueControl(action="start", expected_revision=paused["revision"]))
    work = await queue.claim(db_session, "naukri", {"worker": "restarted"})
    assert work["operation"] == "inspect_profile"
    assert not work["admitted_actions"]


@pytest.mark.parametrize("attempts,enabled", [(2, True), (3, True), (3, False)])
async def test_exhausted_unknown_attempt_notifies_once_without_counting_a_submission(db_session, upload_case, attempts, enabled):
    from pydantic import SecretStr

    from backend.app.local_agent.models import TelegramDelivery

    case = upload_case
    context, item, work = await apply_ready(db_session, case)
    work = await admit(db_session, case, context, work)
    await finish(db_session, case, context, work, {"kind": "failed", "reason": "fictional_lost_response"})
    row = await queue.load(db_session, item["id"])
    row.value = {**row.value, "reconciliation_attempts": attempts}
    config = await queue.configuration(db_session)
    policy = config["policy"]
    policy["platforms"]["naukri"]["notify_telegram"] = enabled
    policy["notify_submitted"] = enabled
    await queue.put(db_session, queue.POLICY_KEY, {**config, "policy": policy})
    settings = case.settings.model_copy(update={"TELEGRAM_BOT_TOKEN": SecretStr("fictional-only"), "TELEGRAM_OWNER_CHAT_ID": 123, "TELEGRAM_OWNER_USER_ID": 456})
    saved = dict(row.value)
    assert await submission.notify_unknown(db_session, saved, settings) is (attempts == 3 and enabled)
    assert not await submission.notify_unknown(db_session, saved, settings)
    await db_session.commit()
    notices = (await db_session.scalars(select(Notification).where(Notification.kind == "application_submission_unknown"))).all()
    deliveries = (await db_session.scalars(select(TelegramDelivery))).all()
    assert len(notices) == len(deliveries) == int(attempts == 3 and enabled)
    if notices:
        assert "unconfirmed" in notices[0].title
        assert "will not be repeated" in notices[0].body
        assert deliveries[0].state == "pending"
    value = (await queue.load(db_session, item["id"])).value
    assert value["stage"] == "SUBMISSION_UNKNOWN" and value["admitted_actions"] == saved["admitted_actions"]
    assert len(value["admitted_actions"]) == 1
    assert not await prevents_replay(db_session, item["requisition"])  # No fabricated receipt.
