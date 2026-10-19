"""Recipient reliability is separate from draft review and never implies sending."""

from datetime import timedelta

import pytest
from sqlalchemy import delete

from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.schemas.outreach import DraftInput
from backend.app.services.outreach_drafting import OutreachDraftingService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,blocker",
    [
        ("suppressed", "contact_suppressed"),
        ("candidate", "unreliable_or_speculative_recipient"),
        ("invalid", "unreliable_or_speculative_recipient"),
        ("no_email", "business_email_required"),
        ("personal_email", "business_email_required"),
        ("identity", "identity_conflict"),
        ("expired", "contact_evidence_expired"),
        ("employer", "current_employer_evidence_required"),
        ("no_projects", "verified_project_contribution_required"),
        ("no_profile", "candidate_profile_required"),
    ],
)
async def test_draft_blockers(
    outreach_target, phase2_profile, db_session, failure, blocker
):
    contact, _, _, evidence = outreach_target
    if failure == "suppressed":
        contact.do_not_contact = True
    elif failure in {"candidate", "invalid"}:
        contact.email_status = failure
    elif failure == "no_email":
        contact.email = None
    elif failure == "personal_email":
        contact.email = "someone@gmail.com"
    elif failure == "identity":
        contact.metadata_ = {"identity_review_required": True}
    elif failure == "expired":
        contact.last_checked_at = now() - timedelta(days=100)
    elif failure == "employer":
        evidence.observed_company = "Different employer"
    elif failure == "no_projects":
        phase2_profile.projects = []
    else:
        await db_session.execute(delete(CandidateProfile))
    await db_session.commit()
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=contact.id, use_llm=False)
    )
    assert (
        result["status"] == "needs_input" and blocker in result["missing_information"]
    )


@pytest.mark.asyncio
async def test_provider_reported_address_warning_not_send_ready(
    outreach_target, db_session
):
    result = await OutreachDraftingService(db_session).create(
        DraftInput(contact_id=outreach_target[0].id, use_llm=False)
    )
    assert result["eligibility"]["eligible_for_approval"]
    assert not result["eligibility"]["email_send_ready"]
    assert (
        "provider_reported_email_is_not_verified" in result["eligibility"]["warnings"]
    )
    assert (
        result["gmail_draft_id"] is None
        and result["gmail_message_id"] is None
        and result["sent_at"] is None
    )


@pytest.mark.asyncio
async def test_expired_identity_evidence_blocks(outreach_target, db_session):
    contact, _, _, evidence = outreach_target
    evidence.expires_at = now() - timedelta(seconds=1)
    await db_session.commit()
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=contact.id, use_llm=False)
    )
    assert "current_employer_evidence_required" in result["missing_information"]


@pytest.mark.asyncio
async def test_job_must_belong_to_contact_employer(outreach_target, db_session):
    from backend.tests.phase4a_fakes import target

    other = await target(db_session, suffix="other")
    with pytest.raises(ValueError, match="employer"):
        await OutreachDraftingService(db_session).preview(
            DraftInput(
                contact_id=outreach_target[0].id, job_id=other[2].id, use_llm=False
            )
        )


@pytest.mark.asyncio
async def test_contact_evidence_deletion_invalidates(outreach_target, db_session):
    service = OutreachDraftingService(db_session)
    result = await service.create(
        DraftInput(contact_id=outreach_target[0].id, use_llm=False)
    )
    await db_session.execute(delete(ContactEvidence))
    await db_session.commit()
    checked = await service.read(result["id"])
    assert not checked["eligibility"]["eligible_for_approval"]


@pytest.mark.asyncio
async def test_generic_inbox_not_personal_recipient(outreach_target, db_session):
    contact = outreach_target[0]
    contact.email = "careers@one.example.com"
    await db_session.commit()
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=contact.id, use_llm=False)
    )
    assert "person_specific_business_email_required" in result["missing_information"]
