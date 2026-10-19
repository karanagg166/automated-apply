"""Real saved candidate/project/context grounding with an injected Gemini abstraction."""

import pytest
from sqlalchemy import func, select

from backend.app.models.outreach import OutreachLog
from backend.app.schemas.outreach import DraftInput
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.outreach_drafting import OutreachDraftingService
from backend.tests.phase2a_fakes import FakeProvider
from backend.tests.phase4a_fakes import target


@pytest.mark.asyncio
async def test_personalized_gemini_draft_reuses_budget(
    outreach_target, db_session, phase2_settings
):
    contact, company, job, _ = outreach_target
    provider = FakeProvider()
    answer = ApplicationAnswerService(db_session, phase2_settings, provider=provider)
    service = OutreachDraftingService(db_session, phase2_settings, answer)
    result = await service.preview(DraftInput(contact_id=contact.id, job_id=job.id))
    assert result["status"] == "draft_ready", result
    assert contact.full_name in result["body"] and company.name in result["body"]
    assert job.title in result["body"] and "Example Relay" in result["body"]
    assert "Python" in result["body"] and "github.com/example" in result["body"]
    assert result["evidence_references"] and result["requires_review"]
    assert result["provider_metadata"]["used_llm"]
    assert len(provider.calls) == 1
    assert await db_session.scalar(select(func.count()).select_from(OutreachLog)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "style", ["professional", "concise", "friendly", "technical", "founder-focused"]
)
async def test_writing_styles_and_mcp_no_billable_call(
    outreach_target, db_session, style
):
    contact, _, job, _ = outreach_target
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=contact.id, job_id=job.id, writing_style=style),
        origin="mcp",
    )
    assert result["status"] == "draft_ready"
    assert result["provider_metadata"]["used_llm"] is False
    assert len(result["body"]) <= 1800
    if style == "friendly":
        assert result["body"].startswith("Hi ")


@pytest.mark.asyncio
async def test_distinct_company_context(db_session, outreach_target):
    other_contact, other_company, other_job, _ = await target(db_session, suffix="two")
    request = DraftInput(
        contact_id=other_contact.id, job_id=other_job.id, use_llm=False
    )
    result = await OutreachDraftingService(db_session).preview(request)
    assert other_company.name in result["body"]
    assert outreach_target[1].name not in result["body"]


@pytest.mark.asyncio
async def test_no_hiring_or_familiarity_inference(outreach_target, db_session):
    contact = outreach_target[0]
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=contact.id, purpose="exploratory", use_llm=False)
    )
    assert "potential engineering opportunities" in result["body"]
    assert "saved" not in result["subject"]
    assert not any(
        term in result["body"].casefold()
        for term in ("actively hiring", "as we discussed", "referral", "following up")
    )


@pytest.mark.asyncio
async def test_unsupported_llm_claim_rejected(
    outreach_target, db_session, phase2_settings
):
    provider = FakeProvider(
        answer="I scaled millions of users and won an international award."
    )
    service = OutreachDraftingService(
        db_session,
        phase2_settings,
        ApplicationAnswerService(db_session, phase2_settings, provider),
    )
    result = await service.preview(DraftInput(contact_id=outreach_target[0].id))
    assert result["status"] == "validation_failed"
    assert result["body"] is None and result["unsupported_claim_flags"]


@pytest.mark.asyncio
async def test_llm_unconfigured_does_not_fabricate(outreach_target, db_session):
    result = await OutreachDraftingService(db_session).preview(
        DraftInput(contact_id=outreach_target[0].id)
    )
    assert result["status"] == "needs_input"
    assert result["missing_information"]
    assert result["body"] is None
