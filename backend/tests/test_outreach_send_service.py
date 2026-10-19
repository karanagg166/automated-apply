"""Real shared eligibility checks; sending never generates or edits approved text."""

import base64
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import select

from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.discovery import now
from backend.app.models.outreach import OutreachLog
from backend.app.models.outreach_send import OutreachSendAttempt
from backend.app.schemas.outreach import DraftEdit
from backend.app.services.outreach_drafting import DraftConflict
from backend.tests.phase4b_fakes import request_from


@pytest.mark.asyncio
async def test_success_records_acceptance_and_preserves_revision(sending_bundle):
    service, draft, client, *_ = sending_bundle
    preview = await service.preview(draft["id"])
    result = await service.send(draft["id"], request_from(preview))
    assert (
        result["status"] == "accepted_by_gmail"
        and result["accepted_at"]
        and result["attempted_at"]
    )
    assert (
        result["gmail_message_id"] == "mock-message-123"
        and not result["reconciliation_required"]
    )
    assert "delivered" not in str(result)
    mime = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(client.calls[0][1])
    )
    assert (
        str(mime["From"]) == preview["sender"]
        and str(mime["To"]) == preview["recipient"]
    )
    assert str(mime["Subject"]) == draft["subject"]
    current = await service.drafts.read(draft["id"])
    assert current["draft_revision"] == draft["draft_revision"]
    assert (
        current["approval_status"] == "approved"
        and current["delivery_status"] == "accepted_by_gmail"
    )
    assert current["gmail_message_id"] == "mock-message-123" and current["sent_at"]
    assert current["outbound_messages_sent"] == 1
    with pytest.raises(DraftConflict, match="immutable"):
        await service.drafts.edit(
            draft["id"],
            DraftEdit(expected_revision=draft["draft_revision"], body="changed"),
        )
    history = await service.history()
    assert history["total"] == 1 and history["messages"][0]["id"] == result["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "unapproved",
        "revision",
        "approval_hash",
        "recipient",
        "profile",
        "suppressed",
        "expired_evidence",
        "provider_reported",
        "candidate",
        "unverified_mailbox",
        "identity_conflict",
        "employer",
        "disconnect",
        "scope",
        "sender_identity",
        "edit_after_approval",
        "expired_candidate_fact",
    ],
)
async def test_revalidation_blockers_never_send(sending_bundle, change):
    service, approved, client, contact, evidence, mailbox = sending_bundle
    preview = await service.preview(approved["id"])
    draft = await service.session.get(OutreachLog, approved["id"])
    account = await service.connection.account()
    if change == "unapproved":
        draft.approval_status = "pending_approval"
    elif change == "revision":
        draft.draft_revision += 1
    elif change == "approval_hash":
        draft.approval_hash = "0" * 64
    elif change == "recipient":
        contact.email = "different@one.example.com"
    elif change in {"profile", "expired_candidate_fact"}:
        profile = await service.session.scalar(select(CandidateProfile))
        profile.projects = (
            [] if change == "expired_candidate_fact" else profile.projects
        )
        profile.summary = "Changed facts require review"
    elif change == "suppressed":
        contact.do_not_contact = True
    elif change == "expired_evidence":
        evidence.expires_at = now() - timedelta(seconds=1)
    elif change in {"provider_reported", "candidate"}:
        contact.email_status = change
    elif change == "unverified_mailbox":
        mailbox.user_confirmed = False
    elif change == "identity_conflict":
        contact.metadata_ = dict(contact.metadata_ or {}) | {
            "identity_review_required": True
        }
    elif change == "employer":
        evidence.observed_company = "Different employer"
    elif change == "disconnect":
        await service.connection.disconnect()
    elif change == "scope":
        account.granted_scopes = [
            s for s in account.granted_scopes if not s.endswith("gmail.send")
        ]
    elif change == "sender_identity":
        account.google_subject = "other-subject"
    elif change == "edit_after_approval":
        await service.drafts.edit(
            draft.id,
            DraftEdit(
                expected_revision=draft.draft_revision,
                body=draft.body + " Extra claim.",
            ),
        )
    await service.session.commit()
    with pytest.raises(DraftConflict):
        await service.send(approved["id"], request_from(preview))
    assert not client.calls and not await service.session.scalar(
        select(OutreachSendAttempt.id)
    )


@pytest.mark.asyncio
async def test_history_preserves_local_review_without_fake_delivery(sending_bundle):
    service, draft, client, *_ = sending_bundle
    history = await service.history()
    assert history["total"] == 1 and history["messages"][0]["draft_id"] == draft["id"]
    assert history["messages"][0]["status"] == "not_attempted"
    assert history["messages"][0]["approval_status"] == "approved"
    assert history["messages"][0]["accepted_at"] is None and not client.calls
