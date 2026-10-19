"""External side effects survive ambiguous responses and process interruption without retries."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.app.integrations.gmail.schemas import SendFailure
from backend.app.models.discovery import now
from backend.app.models.outreach_send import OutreachSendAttempt
from backend.app.services.outreach_drafting import DraftConflict
from backend.tests.phase4b_fakes import request_from


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,uncertain",
    [
        ("credential_rejected", False),
        ("scope_or_policy_denied", False),
        ("gmail_quota_exceeded", False),
        ("gmail_server_or_unexpected_response", True),
        ("transmission_outcome_unknown", True),
        ("connection_failed_before_send", False),
        ("invalid_gmail_response", True),
    ],
)
async def test_failures_are_durable_and_never_retried(
    sending_bundle, category, uncertain
):
    service, draft, client, *_ = sending_bundle
    client.failure = SendFailure(category, uncertain=uncertain)
    request = request_from(await service.preview(draft["id"]))
    first = await service.send(draft["id"], request)
    assert first["status"] == ("outcome_unknown" if uncertain else "failed_before_send")
    assert (
        first["reconciliation_required"] == uncertain
        and first["gmail_message_id"] is None
    )
    again = await service.send(draft["id"], request)
    assert again["id"] == first["id"] and len(client.calls) == 1
    with pytest.raises(DraftConflict):
        await service.send(
            draft["id"],
            request.model_copy(update={"idempotency_key": "different-key-456"}),
        )
    if category in {"credential_rejected", "scope_or_policy_denied"}:
        assert (await service.connection.account()).status == "reauthorization_required"


class ProcessDeath(BaseException):
    pass


@pytest.mark.asyncio
async def test_process_crash_after_external_send_stays_uncertain(sending_bundle):
    service, draft, client, *_ = sending_bundle
    client.failure = ProcessDeath()
    request = request_from(await service.preview(draft["id"]))
    with pytest.raises(ProcessDeath):
        await service.send(draft["id"], request)
    await service.session.rollback()
    attempt = await service.session.scalar(select(OutreachSendAttempt))
    assert attempt.status == "attempting" and attempt.reconciliation_required
    attempt.attempted_at = now() - timedelta(minutes=5)
    await service.session.commit()
    status = await service.status(attempt.id)
    assert status["status"] == "outcome_unknown" and status["reconciliation_required"]
    again = await service.send(draft["id"], request)
    assert again["status"] == "outcome_unknown" and len(client.calls) == 1


@pytest.mark.asyncio
async def test_failure_recording_provider_response_never_resends(
    sending_bundle, monkeypatch
):
    service, draft, client, *_ = sending_bundle
    request = request_from(await service.preview(draft["id"]))
    original_send = client.send
    original_commit = service.session.commit

    async def provider_accepted(token, raw):
        result = await original_send(token, raw)

        async def cannot_commit():
            raise OperationalError(
                "fictional", {}, Exception("private upstream detail")
            )

        monkeypatch.setattr(service.session, "commit", cannot_commit)
        return result

    monkeypatch.setattr(client, "send", provider_accepted)
    result = await service.send(draft["id"], request)
    assert result["status"] == "attempting" and result["reconciliation_required"]
    assert result["failure_category"] == "provider_result_persistence_failed"
    assert "private" not in str(result)
    monkeypatch.setattr(service.session, "commit", original_commit)
    assert (await service.send(draft["id"], request))["status"] == "attempting"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_process_crash_after_reservation_before_dispatch(
    sending_bundle, monkeypatch
):
    service, draft, client, *_ = sending_bundle
    request = request_from(await service.preview(draft["id"]))
    original_commit = service.session.commit

    async def crash_after_claim():
        await original_commit()
        if await service.session.scalar(select(OutreachSendAttempt.id)):
            raise ProcessDeath()

    monkeypatch.setattr(service.session, "commit", crash_after_claim)
    with pytest.raises(ProcessDeath):
        await service.send(draft["id"], request)
    monkeypatch.setattr(service.session, "commit", original_commit)
    await service.session.rollback()
    attempt = await service.session.scalar(select(OutreachSendAttempt))
    assert attempt.status == "prepared" and not client.calls
    attempt.created_at = now() - timedelta(minutes=5)
    await service.session.commit()
    result = await service.status(attempt.id)
    assert (
        result["status"] == "failed_before_send"
        and not result["reconciliation_required"]
    )
    assert (await service.send(draft["id"], request))["id"] == result["id"]
    assert not client.calls
