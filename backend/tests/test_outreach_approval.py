"""Approvals bind text, recipient, evidence and revision; never to delivery."""

import pytest

from backend.app.schemas.outreach import DraftEdit, DraftInput
from backend.app.services.outreach_drafting import (
    DraftConflict,
    OutreachDraftingService,
)


@pytest.mark.asyncio
async def test_revision_specific_approval_and_edit_invalidation(
    outreach_target, db_session
):
    service = OutreachDraftingService(db_session)
    draft = await service.create(
        DraftInput(contact_id=outreach_target[0].id, use_llm=False)
    )
    approved = await service.decide(draft["id"], draft["draft_revision"], True)
    assert approved["approval_status"] == "approved"
    assert approved["eligibility"]["approval_current"]
    assert approved["approved_revision"] == approved["draft_revision"]
    assert approved["sent_at"] is None and approved["gmail_message_id"] is None
    edited = await service.edit(
        draft["id"],
        DraftEdit(
            expected_revision=approved["draft_revision"],
            body=approved["body"] + "\nI founded an international unicorn.",
        ),
    )
    assert edited["approval_status"] == "pending_approval"
    assert (
        edited["approved_at"] is None and not edited["eligibility"]["approval_current"]
    )
    assert (
        "unsupported_edited_claim_requires_grounding"
        in edited["eligibility"]["blockers"]
    )
    with pytest.raises(DraftConflict):
        await service.decide(draft["id"], edited["draft_revision"], True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["recipient", "profile", "evidence", "suppression"])
async def test_material_changes_require_review(
    outreach_target, phase2_profile, db_session, change
):
    service = OutreachDraftingService(db_session)
    contact, _, _, evidence = outreach_target
    draft = await service.create(DraftInput(contact_id=contact.id, use_llm=False))
    approved = await service.decide(draft["id"], draft["draft_revision"], True)
    if change == "recipient":
        contact.email = "other@one.example.com"
    elif change == "profile":
        phase2_profile.summary = "Changed candidate context"
    elif change == "evidence":
        evidence.observed_role = "Former CTO"
    else:
        contact.do_not_contact = True
    await db_session.commit()
    current = await service.read(approved["id"])
    assert not current["eligibility"]["approval_current"]
    assert not current["eligibility"]["eligible_for_approval"]


@pytest.mark.asyncio
async def test_recipient_edit_clears_approval(outreach_target, db_session):
    service = OutreachDraftingService(db_session)
    draft = await service.create(
        DraftInput(contact_id=outreach_target[0].id, use_llm=False)
    )
    approved = await service.decide(draft["id"], draft["draft_revision"], True)
    changed = await service.edit(
        draft["id"],
        DraftEdit(
            expected_revision=approved["draft_revision"],
            recipient_email="different@one.example.com",
        ),
    )
    assert changed["approval_status"] == "pending_approval"
    assert not changed["eligibility"]["eligible_for_approval"]


@pytest.mark.asyncio
async def test_rejection_and_stale_revision(outreach_target, db_session):
    service = OutreachDraftingService(db_session)
    draft = await service.create(
        DraftInput(contact_id=outreach_target[0].id, use_llm=False)
    )
    rejected = await service.decide(draft["id"], draft["draft_revision"], False)
    assert rejected["approval_status"] == "rejected"
    with pytest.raises(DraftConflict):
        await service.decide(draft["id"], rejected["draft_revision"], True)
    with pytest.raises(DraftConflict, match="revision"):
        await service.edit(
            draft["id"], DraftEdit(expected_revision=1, body="A stale edit")
        )


@pytest.mark.asyncio
async def test_idempotency_request_and_origin_binding(outreach_target, db_session):
    service = OutreachDraftingService(db_session)
    request = DraftInput(
        contact_id=outreach_target[0].id,
        use_llm=False,
        idempotency_key="outreach-key-123",
    )
    first = await service.create(request)
    second = await service.create(request)
    assert first["id"] == second["id"]
    with pytest.raises(DraftConflict, match="idempotency"):
        await service.create(request.model_copy(update={"writing_style": "technical"}))
    with pytest.raises(DraftConflict, match="idempotency"):
        await service.create(request, origin="mcp")
