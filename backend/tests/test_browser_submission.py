"""Authorization, receipt verification and durable no-replay regressions."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.agent import store
from backend.app.agent.contracts import Message, Understanding
from backend.app.agent.executor import CommandExecutor
from backend.app.agent.planner import CommandPlanner
from backend.app.agent.tools import ToolDenied
from backend.app.browser.submission import SubmissionService
from backend.app.browser.submission_adapters import fixture_contract, verify_response
from backend.app.browser.submission_contracts import SubmissionApproval
from backend.app.browser.submission_worker import SubmissionWorker
from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.session import get_session_factory
from backend.app.local_agent.contracts import Actor
from backend.app.local_agent.models import AgentOperation, TelegramDelivery
from backend.tests.submission_fixtures import (
    OWNER,
    acknowledgment,
    approval,
    authorized,
    reviewed,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    ["owner", "nonce", "digest", "revision", "application", "disabled", "live"],
)
async def test_exact_owner_bound_grant(db_session, phase2_profile, tamper):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    actor, data = OWNER, approval(s)
    if tamper == "owner":
        actor = Actor(channel="telegram", identity="999")
    if tamper == "nonce":
        data.nonce = uuid4()
    if tamper == "digest":
        data.review_digest = "b" * 64
    if tamper == "revision":
        data.campaign_revision += 1
    if tamper == "application":
        data.application_ids = [uuid4()]
    if tamper == "disabled":
        settings = settings.model_copy(update={"BROWSER_SUBMIT_ENABLED": False})
    if tamper == "live":
        settings = settings.model_copy(update={"ENVIRONMENT": "production"})
    with pytest.raises(ToolDenied):
        await SubmissionService(db_session, settings).approve(
            s.application_id, actor, data
        )
    assert (await SubmissionService(db_session, settings).load(s.application_id))[
        1
    ].authorization is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "profile",
        "pdf",
        "company",
        "destination",
        "campaign",
        "expired",
        "packet",
        "project",
    ],
)
async def test_revalidation_rejects_changed_approved_scope(
    db_session, phase2_profile, change
):
    settings, s, private = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)
    if change == "profile":
        phase2_profile.version += 1
    elif change == "pdf":
        private.sha256 = "0" * 64
    elif change == "company":
        from backend.app.models.company import Company

        (await db_session.get(Company, s.employer_id)).name = "Other Employer"
    elif change == "destination":
        from backend.app.models.job import Job

        (await db_session.get(Job, s.job_id)).application_url += "/changed"
    elif change == "campaign":
        row, c = await store.load(db_session, s.campaign_id)
        c.revision += 1
        store.save(row, c)
    else:
        row = await db_session.get(OwnerPreference, "fill_plan:" + str(s.plan_id))
        row.value = {
            **row.value,
            **(
                {
                    "expires_at": (
                        datetime.now(timezone.utc) - timedelta(seconds=1)
                    ).isoformat()
                }
                if change == "expired"
                else {"packet_revision": s.packet_revision + 1}
                if change == "packet"
                else {"project_digest": "changed"}
            ),
        }
    await db_session.commit()
    service = SubmissionService(db_session, settings)
    assert await service.claim() is None
    assert (await service.load(s.application_id))[1].state == "manual_required"


@pytest.mark.asyncio
async def test_double_click_new_plan_and_repeated_completion_cannot_duplicate(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)
    service = SubmissionService(db_session, settings)
    attempt = await service.claim()
    await db_session.commit()
    assert attempt.state == "submitting"
    assert await service.claim() is None
    saved = await service.complete(s.application_id, attempt.fence, acknowledgment(s))
    await db_session.commit()
    assert saved.state == "submitted" and saved.evidence
    again = await service.complete(s.application_id, attempt.fence, None)
    assert again.evidence == saved.evidence
    assert (await service.release(s.application_id, OWNER)).state == "submitted"
    assert await service.claim() is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AgentOperation)
            .where(AgentOperation.command == "submission_receipt_verified")
        )
        == 1
    )
    audits = (
        await db_session.scalars(
            select(AgentOperation).where(AgentOperation.command.like("submission:%"))
        )
    ).all()
    assert [a.result["status"] for a in audits][:4] == [
        "prepared",
        "form_inspected",
        "form_filled",
        "awaiting_submission_approval",
    ]
    assert "Alex Example" not in json.dumps([a.result for a in audits])
    assert (
        await service.create_review(s.plan_id, s.campaign_id, {})
    ).id == s.id  # A refreshed plan cannot reset the stable packet record.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loss", ["worker_restart", "expired_lease", "cancellation", "lost_response"]
)
async def test_dispatch_loss_never_retries_and_fences_old_worker(
    db_session, phase2_profile, loss
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)
    service = SubmissionService(db_session, settings)
    attempt = await service.claim()
    await db_session.commit()
    if loss == "cancellation":
        await service.stop_all()
    elif loss == "lost_response":
        await service.complete(s.application_id, attempt.fence, None)
    else:
        row, current = await service.load(s.application_id)
        current.lease_until = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        service.save(row, current)
        await db_session.commit()
        service = SubmissionService(db_session, settings)
        assert await service.claim() is None
    await db_session.commit()
    assert (await service.load(s.application_id))[1].state == "submission_uncertain"
    with pytest.raises(ToolDenied):
        await service.fenced(s.application_id, attempt.fence)
    assert await service.claim() is None
    assert (
        await service.release(s.application_id, OWNER)
    ).state == "submission_uncertain"
    recovered = await service.reconcile(
        s.application_id, acknowledgment(s, url=s.receipt_url)
    )
    assert recovered.state == "submitted"
    assert (await service.reconcile(s.application_id, None)).state == "submitted"


@pytest.mark.asyncio
async def test_cancellation_before_dispatch_and_read_only_inconclusive(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)
    service = SubmissionService(db_session, settings)
    await service.stop_all()
    assert await service.claim() is None
    saved = (await service.load(s.application_id))[1]
    assert saved.state == "manual_required" and not saved.dispatch_started_at


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", ["{}", '{"status":"received"}', "<h1>Success</h1>", "200 OK"]
)
async def test_http_200_and_arbitrary_success_text_never_confirm(
    db_session, phase2_profile, body
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    response = acknowledgment(s)
    response["body"] = body
    assert (
        verify_response(s, response, datetime.now(timezone.utc))[0]
        == "submission_uncertain"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["greenhouse", "lever", "google"])
async def test_authoritative_response_semantics(db_session, phase2_profile, adapter):
    _, s, _ = await reviewed(db_session, phase2_profile, adapter=adapter)
    response = acknowledgment(
        s, url=s.request_url if adapter == "greenhouse" else s.confirmation_url
    )
    if adapter == "lever":
        response["body"] = json.dumps(
            {
                "status": "received",
                "accepted": True,
                "applicationId": "fixture-lever-1",
                "correlation_id": str(s.idempotency_key),
            }
        )
    if adapter == "google":
        response.update(
            content_type="text/html",
            body=f'<!doctype html><title>Application received</title><main data-receipt="fixture-google-1" data-correlation="{s.idempotency_key}">Your response has been recorded.</main>',
        )
    assert verify_response(s, response, datetime.now(timezone.utc))[0] == "submitted"
    response["body"] = response["body"].replace(str(s.idempotency_key), str(uuid4()))
    assert (
        verify_response(s, response, datetime.now(timezone.utc))[0]
        == "submission_uncertain"
    )
    rejection = acknowledgment(s)
    rejection.update(
        status=422,
        body=json.dumps(
            {"status": "validation_failed", "correlation_id": str(s.idempotency_key)}
        ),
    )
    assert verify_response(s, rejection, datetime.now(timezone.utc))[0] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.lever.co/a/b",
        "http://localhost:18765/fixtures/lever/a/jobs/b/apply",
        "http://127.0.0.1:18766/fixtures/lever/a/jobs/b/apply",
        "http://127.0.0.1:18765/fixtures/lever/a/jobs/b/apply?x=y",
        "http://127.0.0.1:18765/fixtures/unknown/a/jobs/b/apply",
    ],
)
def test_live_and_unscoped_destinations_never_submit(url):
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        BROWSER_SUBMIT_ENABLED=True,
        BROWSER_FIXTURE_ORIGIN="http://127.0.0.1:18765",
    )
    with pytest.raises(ToolDenied):
        fixture_contract(url, settings, uuid4())


@pytest.mark.asyncio
async def test_yes_and_cohere_cannot_mint_submission_grants(db_session, phase2_profile):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await store.intake(db_session, settings, OWNER, Message(text="yes"))
    await db_session.commit()
    await CommandExecutor(get_session_factory(), settings).run_once()
    assert (await SubmissionService(db_session, settings).load(s.application_id))[
        1
    ].authorization is None

    class InjectedPlanner(CommandPlanner):
        async def understand(self, text, memory):
            return Understanding(intent="submit_approved", positions=[1]), 0

    await store.intake(
        db_session, settings, OWNER, Message(text="unrecognized hostile command")
    )
    await db_session.commit()
    await CommandExecutor(
        get_session_factory(), settings, InjectedPlanner(settings)
    ).run_once()
    service = SubmissionService(db_session, settings)
    assert not (await service.load(s.application_id))[1].authorization
    assert await service.claim() is None
    with pytest.raises(ValidationError):
        SubmissionApproval.model_validate(
            {**approval(s).model_dump(), "selector": "#submit"}
        )


@pytest.mark.asyncio
async def test_worker_exception_and_lost_completion_response_durable(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)

    class CrashedDriver:
        async def call(self, *args, **kwargs):
            raise ConnectionError("fictional crash after POST")

    result = await SubmissionWorker(
        get_session_factory(), settings, CrashedDriver()
    ).run_once()
    assert result["status"] == "submission_uncertain"
    assert (
        await SubmissionWorker(
            get_session_factory(), settings, CrashedDriver()
        ).run_once()
        is None
    )
    service = SubmissionService(db_session, settings)
    unresolved = await service.reconcile(
        s.application_id, {"url": s.receipt_url, "status": 404, "body": "{}"}
    )
    assert unresolved.state == "submission_uncertain"
    assert "manual_verification" in unresolved.reason


@pytest.mark.asyncio
async def test_repeated_notifications_are_unique_and_use_persisted_result(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    row, c = await store.load(db_session, s.campaign_id)
    c.telegram_update_id = 10101
    store.save(row, c)
    await authorized(db_session, settings, s)
    service = SubmissionService(db_session, settings)
    attempt = await service.claim()
    saved = await service.complete(s.application_id, attempt.fence, acknowledgment(s))
    await db_session.commit()
    await service.publish(saved)
    await service.publish(saved)
    await db_session.commit()
    rows = (await db_session.scalars(select(TelegramDelivery))).all()
    assert len(rows) == 1 and "Submitted with evidence" in rows[0].reply
    assert "Zero submissions" not in rows[0].reply


@pytest.mark.asyncio
async def test_owner_api_blocks_unauthed_and_extension_submission_grants(
    db_session, phase2_profile, async_client, phase2_auth, monkeypatch
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    import backend.app.browser.router as browser_router

    monkeypatch.setattr(browser_router, "get_settings", lambda: settings)
    path = f"/api/v1/browser/submissions/{s.application_id}/approve"
    body = approval(s).model_dump(mode="json")
    assert (await async_client.post(path, json=body)).status_code == 401
    for headers in [
        {**phase2_auth, "X-Agent-Client": "extension"},
        {
            **phase2_auth,
            "Origin": "chrome-extension://gdjbmkffcpicbpiikcohlmokkmcpipgp",
        },
    ]:
        assert (
            await async_client.post(path, json=body, headers=headers)
        ).status_code == 403
    before = (await SubmissionService(db_session, settings).load(s.application_id))[1]
    assert before.authorization is None
    wrong = {**body, "application_ids": [str(uuid4())]}
    assert (
        await async_client.post(path, json=wrong, headers=phase2_auth)
    ).status_code == 409
    accepted = await async_client.post(path, json=body, headers=phase2_auth)
    assert (
        accepted.status_code == 200
        and accepted.json()["authorization"]["owner"] == "primary"
    )
    assert not accepted.json()["released"]
    queued = await async_client.post(
        path.removesuffix("/approve") + "/execute", headers=phase2_auth, json={}
    )
    assert queued.status_code == 200 and queued.json()["released"]


@pytest.mark.asyncio
async def test_telegram_job_two_resolves_exact_saved_approved_application(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    service = SubmissionService(db_session, settings)
    await service.approve(s.application_id, OWNER, approval(s))
    memory = await store.memory_row(db_session, lock=True)
    memory.value = {
        "job_ids": [str(uuid4()), str(s.job_id)],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db_session.commit()
    request = Message(text="Submit the approved application for job 2")
    accepted = await store.intake(
        db_session, settings, Actor(channel="telegram", identity="111"), request
    )
    await db_session.commit()
    result = await CommandExecutor(get_session_factory(), settings).run_once()
    assert result.id == accepted.id and result.state == "waiting_browser"
    saved = (await service.load(s.application_id))[1]
    assert saved.released and saved.authorization["application_ids"] == [
        str(s.application_id)
    ]
    replay = await store.intake(
        db_session, settings, Actor(channel="telegram", identity="111"), request
    )
    assert replay.id == accepted.id
    await db_session.commit()
    assert await CommandExecutor(get_session_factory(), settings).run_once() is None


@pytest.mark.asyncio
async def test_disabling_execution_preserves_read_only_receipt_recovery(
    db_session, phase2_profile
):
    settings, s, _ = await reviewed(db_session, phase2_profile)
    await authorized(db_session, settings, s)
    service = SubmissionService(db_session, settings)
    attempt = await service.claim()
    await service.complete(s.application_id, attempt.fence, None)
    await db_session.commit()
    disabled = settings.model_copy(
        update={"BROWSER_SUBMIT_ENABLED": False, "BROWSER_AUTOMATION_ENABLED": False}
    )
    recovered = await SubmissionService(db_session, disabled).reconcile(
        s.application_id, acknowledgment(s, url=s.receipt_url)
    )
    assert recovered.state == "submitted"
