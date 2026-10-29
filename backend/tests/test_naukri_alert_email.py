"""Potential alert source, fictional Gmail responses only; never visits Naukri."""

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import alert_email, recurring
from backend.app.execution.contracts import AutomationPolicyUpdate
from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
from backend.app.integrations.token_store import ConnectionError
from backend.tests.phase4a_fakes import GoogleFixture, oauth_settings
from backend.tests.test_naukri_recurring import prepared_policy as prepared_policy
from backend.tests.test_naukri_recurring import start
from backend.tests.test_phase3_gmail_readonly import connect

URL = "https://www.naukri.com/job-listings-fictional-backend-281026123456"


@pytest.fixture
def future_adapter_fixture(monkeypatch):
    # Retain dormant adapter contracts using fictional transports only. This is
    # not an environment flag or an activation path in the shipped application.
    monkeypatch.setattr(alert_email, "PHASE54_GMAIL_INTAKE_READY", True)


@pytest.mark.asyncio
async def test_phase53_deferral_cannot_be_overridden_by_gmail_flags(
    db_session, prepared_policy, monkeypatch
):
    settings = oauth_settings(
        GMAIL_READ_SYNC_ENABLED=True, GMAIL_READ_BODY_REVIEWED=True,
        NAUKRI_ALERT_EMAILS_ENABLED=True,
    )
    policy = prepared_policy.model_copy(update={
        "source": "gmail_job_alerts", "gmail_account_id": uuid4(), "gmail_policy_version": 1,
    })
    with pytest.raises(ToolDenied, match="gmail_intake_deferred_to_phase54"):
        await recurring.configure(db_session, AutomationPolicyUpdate(expected_revision=1, policy=policy))
    with pytest.raises(ToolDenied, match="gmail_intake_deferred_to_phase54"):
        await alert_email.source_ready(db_session, policy, settings)

    def deny_reader(*args, **kwargs):
        pytest.fail("Phase 5.3 must not construct a Gmail reader")

    monkeypatch.setattr(alert_email, "GmailReadService", deny_reader)
    monkeypatch.setattr(alert_email, "get_settings", lambda: settings)
    # A previously persisted RUNNING Gmail policy also cannot poll after upgrade.
    value = await recurring.record(db_session)
    await recurring.put(db_session, recurring.KEY, {
        **value, "state": "RUNNING", "policy": policy.model_dump(mode="json"),
    })
    await db_session.commit()
    await alert_email.poll(async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False))
    assert (await recurring.record(db_session))["source_error"] == "gmail_intake_deferred_to_phase54"


def evidence(account_id):
    now = datetime.now(timezone.utc)
    return {
        "id": "fictional-message-digest",
        "account_id": str(account_id),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "observed_at": now.isoformat(),
        "received_at": now.isoformat(),
        "links": [
            URL + "?tracking=discard",
            URL,
            "https://www.naukri.com/redirect?url=x",
            "https://evil.example/job-listings-a-281026123456",
        ],
    }


def test_candidates_retain_uncertainty_and_exact_requisition():
    account = uuid4()
    rows = alert_email.candidates(
        evidence(account), account, datetime.now(timezone.utc)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["url"] == URL and row["requisition_id"] == "281026123456"
    assert row["title"] is None and row["employer"] is None
    assert row["state"] == "NEEDS_INPUT" and row["posting_status"] == "unknown"
    assert row["sender_authenticity"] == "unverified" and row["submitted"] is False
    assert not alert_email.candidates(
        evidence(account), uuid4(), datetime.now(timezone.utc)
    )
    assert not alert_email.candidates(
        evidence(account), account, datetime.now(timezone.utc) + timedelta(days=2)
    )


@pytest.mark.asyncio
async def test_poll_default_never_reads_mailbox(db_session, prepared_policy, future_adapter_fixture):
    policy = prepared_policy.model_copy(
        update={
            "source": "gmail_job_alerts",
            "gmail_account_id": uuid4(),
            "gmail_policy_version": 1,
        }
    )
    await recurring.configure(
        db_session, AutomationPolicyUpdate(expected_revision=1, policy=policy)
    )
    await start(db_session)
    await db_session.commit()
    await alert_email.poll(
        async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    )
    value = await recurring.record(db_session)
    assert value["source_error"] == "naukri_alert_email_activation_required"
    assert value["source_next_at"] and not value.get("source_last_check_at")


@pytest.mark.asyncio
async def test_approved_fake_poll_deduplicates_requisitions_and_keeps_manual_review(
    db_session, prepared_policy, monkeypatch, future_adapter_fixture
):
    settings = oauth_settings(
        GMAIL_READ_SYNC_ENABLED=True,
        GMAIL_READ_BODY_REVIEWED=True,
        NAUKRI_ALERT_EMAILS_ENABLED=True,
    )
    fake = GoogleFixture()
    async with fake.client() as oauth_client:
        account = await connect(
            db_session,
            settings,
            fake,
            oauth_client,
            "alerts-owner@example.com",
            body=True,
        )
    service = GmailReadService(db_session, settings)
    await service.configure(
        account,
        ReadPolicy(
            expected_version=0,
            enabled=True,
            read_body=True,
            body_purpose="Read explicitly selected Naukri job alert links",
            sender_allowlist=["alerts@naukri.com"],
            max_pages=1,
        ),
    )
    policy = prepared_policy.model_copy(
        update={
            "source": "gmail_job_alerts",
            "gmail_account_id": account,
            "gmail_policy_version": 1,
        }
    )
    await recurring.configure(
        db_session, AutomationPolicyUpdate(expected_revision=1, policy=policy)
    )
    await start(db_session)
    await db_session.commit()
    calls = []

    def response(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "gmail.googleapis.com"
        if request.url.path.endswith("/messages"):
            assert "from:alerts@naukri.com" in request.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        payload = {
            "headers": [
                {"name": "From", "value": "alerts@naukri.com"},
                {"name": "Subject", "value": "Backend job alert"},
            ]
        }
        if request.url.params["format"] == "full":
            payload.update(
                mimeType="text/html",
                body={
                    "data": base64.urlsafe_b64encode(
                        f'<a href="{URL}">Backend Developer</a><a href="{URL}?track=x">Apply</a>'.encode()
                    ).decode()
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "threadId": "t1",
                "internalDate": str(
                    int(
                        (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()
                        * 1000
                    )
                ),
                "payload": payload,
            },
        )

    original = GmailReadService
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        monkeypatch.setattr(alert_email, "get_settings", lambda: settings)
        monkeypatch.setattr(
            alert_email,
            "GmailReadService",
            lambda session, settings: original(session, settings, client=client),
        )
        factory = async_sessionmaker(
            db_session.bind, expire_on_commit=False, autoflush=False
        )
        await alert_email.poll(factory)
        value = await recurring.record(db_session)
        assert value["source_error"] is None and value["source_last_check_at"]
        rows = (
            await db_session.scalars(
                select(OwnerPreference).where(
                    OwnerPreference.key.startswith(alert_email.PREFIX)
                )
            )
        ).all()
        assert len(rows) == 1 and rows[0].value["state"] == "NEEDS_INPUT"
        assert rows[0].value["message_references"]
        await db_session.commit()
        await alert_email.poll(factory)
        assert (
            len(calls) == 3
        )  # list + selected metadata + selected body; no repeat before due.
        async with factory() as session, session.begin():
            assert await alert_email.retain_candidates(session, policy) == 0


@pytest.mark.asyncio
async def test_gmail_sync_guard_stops_before_next_http_request(db_session):
    settings = oauth_settings(
        GMAIL_READ_SYNC_ENABLED=True, GMAIL_READ_BODY_REVIEWED=True
    )
    fake = GoogleFixture()
    async with fake.client() as oauth_client:
        account = await connect(
            db_session,
            settings,
            fake,
            oauth_client,
            "alerts-owner@example.com",
            body=True,
        )
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        service = GmailReadService(db_session, settings, client=client)
        await service.configure(
            account,
            ReadPolicy(
                expected_version=0,
                enabled=True,
                read_body=True,
                body_purpose="Review selected Naukri job alerts",
                sender_allowlist=["alerts@naukri.com"],
            ),
        )
        checks = 0

        async def guard():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise ConnectionError("naukri_alert_read_authority_lost")

        with pytest.raises(ConnectionError, match="authority_lost"):
            await service.sync(account, authorization_guard=guard)
        assert len(requests) == 1 and requests[0].url.path.endswith("/messages")
