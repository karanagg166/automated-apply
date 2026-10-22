"""Approved answer reuse never substitutes facts, companies, scopes or stale evidence."""

import pytest
from fastapi import HTTPException

from backend.app.ai.schemas import GenerateRequest
from backend.app.core.config import get_settings
from backend.app.knowledge.reuse import ApproveReuse, approve, revoke
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.phase2a_fakes import FakeProvider


@pytest.fixture
def reuse_enabled(monkeypatch):
    monkeypatch.setenv("APPROVED_ANSWER_REUSE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_paraphrase_reuses_only_explicitly_approved_current_answer(
    db_session, phase2_profile, phase2_settings, reuse_enabled
):
    phase2_settings.APPROVED_ANSWER_REUSE_ENABLED = True
    model = FakeProvider()
    service = ApplicationAnswerService(db_session, phase2_settings, model)
    original = await service.generate(
        GenerateRequest(
            question="Describe a challenging project you built", save_draft=True
        )
    )
    assert original.draft_id
    await CandidateKnowledgeRepository(db_session).review_draft(
        original.draft_id, "reviewed"
    )
    await approve(
        db_session,
        original.draft_id,
        ApproveReuse(
            expected_profile_version=phase2_profile.version,
            scope="general_profile",
            confirm_reviewed_answer=True,
        ),
    )
    await db_session.commit()
    paraphrase = await service.generate(
        GenerateRequest(
            question="Explain a difficult engineering problem you solved in your project"
        )
    )
    assert paraphrase.answer == original.answer
    assert paraphrase.reused_draft_id == original.draft_id
    assert paraphrase.requires_review and not paraphrase.used_llm
    assert len(model.calls) == 1
    await revoke(db_session, original.draft_id)
    await db_session.commit()
    fresh = await service.generate(
        GenerateRequest(question="Describe a challenging project you built")
    )
    assert fresh.reused_draft_id is None
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_motivation_general_scope_and_stale_answer_are_rejected(
    db_session, phase2_profile, phase2_settings, reuse_enabled
):
    from backend.app.models.application_answer import ApplicationAnswerDraft

    draft = ApplicationAnswerDraft(
        candidate_profile_id=phase2_profile.id,
        question="Why do you want to join this company",
        answer="I prefer Python roles.",
        question_category="motivation",
        writing_style="professional",
        candidate_profile_version=phase2_profile.version,
        review_status="reviewed",
        evidence_references=[],
    )
    db_session.add(draft)
    await db_session.flush()
    with pytest.raises(HTTPException, match="Company motivation"):
        await approve(
            db_session,
            draft.id,
            ApproveReuse(
                expected_profile_version=phase2_profile.version,
                scope="general_profile",
                confirm_reviewed_answer=True,
            ),
        )


@pytest.mark.asyncio
async def test_wrong_saved_company_context_never_calls_model(
    db_session, phase2_profile, phase2_settings, application_target
):
    job, _ = application_target
    model = FakeProvider()
    result = await ApplicationAnswerService(
        db_session, phase2_settings, model
    ).generate(
        GenerateRequest(
            question="Why join this company?",
            job_id=job.id,
            company_name="A different company",
        )
    )
    assert result.error_code == "company_context_mismatch"
    assert not model.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["profile", "answer", "evidence", "skill", "style", "length"]
)
async def test_reuse_rejects_stale_bindings_and_different_question_constraints(
    db_session, phase2_profile, phase2_settings, reuse_enabled, change
):
    from backend.app.models.application_answer import (
        ApplicationAnswerDraft,
        CandidateEvidence,
    )

    phase2_settings.APPROVED_ANSWER_REUSE_ENABLED = True
    model = FakeProvider()
    service = ApplicationAnswerService(db_session, phase2_settings, model)
    original = await service.generate(
        GenerateRequest(
            question="Describe a challenging project you built", save_draft=True
        )
    )
    await CandidateKnowledgeRepository(db_session).review_draft(
        original.draft_id, "reviewed"
    )
    await approve(
        db_session,
        original.draft_id,
        ApproveReuse(
            expected_profile_version=phase2_profile.version,
            scope="general_profile",
            confirm_reviewed_answer=True,
        ),
    )
    await db_session.commit()
    kwargs = {"question": "Describe a challenging project you built"}
    if change == "profile":
        phase2_profile.version += 1
    elif change == "answer":
        (
            await db_session.get(ApplicationAnswerDraft, original.draft_id)
        ).answer = "Changed after approval."
    elif change == "evidence":
        db_session.add(
            CandidateEvidence(
                candidate_profile_id=phase2_profile.id,
                evidence_type="other",
                title="New evidence",
                content="I built another service.",
                user_confirmed=True,
            )
        )
    elif change == "skill":
        kwargs["question"] = "Describe a challenging Python project you built"
    elif change == "style":
        kwargs["writing_style"] = "concise"
    elif change == "length":
        kwargs["max_characters"] = 50
    await db_session.commit()
    fresh = await service.generate(GenerateRequest(**kwargs))
    assert fresh.reused_draft_id is None
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_same_job_motivation_never_crosses_company_or_changed_job_context(
    db_session, phase2_profile, phase2_settings, reuse_enabled, application_target
):
    from backend.app.models.application_answer import ApplicationAnswerDraft

    job, _ = application_target
    phase2_profile.preferences = {
        **phase2_profile.preferences,
        "target_titles": ["Backend Engineer"],
    }
    await db_session.flush()
    draft = ApplicationAnswerDraft(
        candidate_profile_id=phase2_profile.id,
        job_id=job.id,
        question="Why do you want to join this company",
        answer="I am interested in the backend role because I prefer backend engineering.",
        question_category="motivation",
        writing_style="professional",
        candidate_profile_version=phase2_profile.version,
        review_status="reviewed",
        evidence_references=[
            {
                "source_type": "candidate_preferences",
                "source_id": str(phase2_profile.id),
            }
        ],
    )
    db_session.add(draft)
    await db_session.flush()
    await approve(
        db_session,
        draft.id,
        ApproveReuse(
            expected_profile_version=phase2_profile.version,
            scope="same_job",
            confirm_reviewed_answer=True,
        ),
    )
    await db_session.commit()
    phase2_settings.APPROVED_ANSWER_REUSE_ENABLED = True
    model = FakeProvider()
    service = ApplicationAnswerService(db_session, phase2_settings, model)
    request = GenerateRequest(
        question="Why would you like to join our company", job_id=job.id
    )
    result = await service.generate(request)
    assert result.reused_draft_id == draft.id
    assert not model.calls
    job.description = "A different role with different responsibilities."
    await db_session.commit()
    fresh = await service.generate(request)
    assert fresh.reused_draft_id is None
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_api_requires_distinct_single_use_owner_proof_for_reuse_approval(
    async_client,
    db_session,
    phase2_profile,
    phase2_settings,
    reuse_enabled,
    phase2_auth,
    monkeypatch,
):
    import json
    import time
    from uuid import uuid4

    from backend.app.browser.owner_approval import approval_header

    owner_key = "fictional-knowledge-owner-approval-key-separate"  # pragma: allowlist secret — fixture only
    monkeypatch.setenv("BROWSER_OWNER_APPROVAL_KEY", owner_key)
    get_settings.cache_clear()
    draft = await ApplicationAnswerService(
        db_session, phase2_settings, FakeProvider()
    ).generate(
        GenerateRequest(question="Describe a project you built", save_draft=True)
    )
    await CandidateKnowledgeRepository(db_session).review_draft(
        draft.draft_id, "reviewed"
    )
    await db_session.commit()
    path = f"/api/v1/application-answers/drafts/{draft.draft_id}/approve-reuse"
    body = json.dumps(
        {
            "expected_profile_version": phase2_profile.version,
            "scope": "general_profile",
            "confirm_reviewed_answer": True,
        }
    ).encode()
    assert (
        await async_client.post(
            path,
            content=body,
            headers={**phase2_auth, "Content-Type": "application/json"},
        )
    ).status_code == 403
    assert (
        await async_client.get("/api/v1/application-answers/reuse-approvals")
    ).status_code == 401
    signed = {
        **phase2_auth,
        "Content-Type": "application/json",
        "X-Browser-Owner-Approval": approval_header(
            owner_key, path, body, nonce=uuid4().hex, timestamp=int(time.time())
        ),
    }
    response = await async_client.post(path, content=body, headers=signed)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert (
        await async_client.post(path, content=body, headers=signed)
    ).status_code == 403
    bank = (
        await async_client.get(
            "/api/v1/application-answers/reuse-approvals", headers=phase2_auth
        )
    ).json()
    assert bank["approvals"][str(draft.draft_id)]["approved"]
    assert (
        await async_client.post(
            path.replace("approve-reuse", "revoke-reuse"), headers=phase2_auth
        )
    ).status_code == 200
    bank = (
        await async_client.get(
            "/api/v1/application-answers/reuse-approvals", headers=phase2_auth
        )
    ).json()
    assert not bank["approvals"][str(draft.draft_id)]["approved"]
