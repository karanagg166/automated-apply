"""Exact preview binding, expiry, replay and actor checks with zero preview side effects."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.app.models.discovery import now
from backend.app.models.outreach_send import SendConfirmation
from backend.app.services.outreach_drafting import DraftConflict
from backend.tests.phase4b_fakes import request_from


@pytest.mark.asyncio
async def test_preview_exact_content_no_send_and_single_use(sending_bundle):
    service, draft, client, *_ = sending_bundle
    preview = await service.preview(draft["id"])
    assert (
        preview["sender"] == "secondary@example.com"
        and preview["recipient"] == draft["recipient_email"]
    )
    assert preview["subject"] == draft["subject"] and preview["body"] == draft["body"]
    assert (
        preview["approval_current"]
        and preview["send_confirmation_required"]
        and not client.calls
    )
    confirmation = await service.session.scalar(select(SendConfirmation))
    assert (
        confirmation.token_hash != preview["confirmation_token"]
        and confirmation.consumed_at is None
    )
    request = request_from(preview)
    first = await service.send(draft["id"], request)
    second = await service.send(draft["id"], request)
    assert first["id"] == second["id"] and len(client.calls) == 1
    with pytest.raises(DraftConflict):
        await service.send(
            draft["id"],
            request.model_copy(update={"idempotency_key": "another-human-key"}),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "expiry",
        "consumed",
        "token",
        "sender",
        "revision",
        "approval",
        "actor",
        "draft",
        "recipient_binding",
        "evidence_binding",
        "content_binding",
        "sender_binding",
    ],
)
async def test_invalid_confirmation_never_invokes_gmail(sending_bundle, change):
    service, draft, client, *_ = sending_bundle
    preview = await service.preview(draft["id"])
    request, key, actor = request_from(preview), draft["id"], "owner"
    confirmation = await service.session.scalar(select(SendConfirmation))
    if change == "expiry":
        confirmation.expires_at = now() - timedelta(seconds=1)
    elif change == "consumed":
        confirmation.consumed_at = now()
    elif change == "token":
        request = request.model_copy(update={"confirmation_token": "x" * 43})
    elif change == "sender":
        request = request.model_copy(update={"sender_account_id": uuid.uuid4()})
    elif change == "revision":
        request = request.model_copy(
            update={"expected_revision": request.expected_revision + 1}
        )
    elif change == "approval":
        request = request.model_copy(update={"approval_hash": "0" * 64})
    elif change == "actor":
        actor = "another-owner"
    elif change == "draft":
        key = uuid.uuid4()
    else:
        field = {
            "recipient_binding": "recipient_email",
            "evidence_binding": "evidence_digest",
            "content_binding": "content_digest",
            "sender_binding": "sender_binding",
        }[change]
        setattr(
            confirmation,
            field,
            "other@example.org" if field == "recipient_email" else "0" * 64,
        )
    await service.session.commit()
    with pytest.raises((DraftConflict, LookupError)):
        await service.send(key, request, actor=actor)
    assert not client.calls
