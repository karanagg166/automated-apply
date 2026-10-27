"""Fictional owner facts: durable abstention, revision, approval and invalidation."""

import json
import time
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.ai.schemas import GenerateRequest
from backend.app.browser.owner_approval import approval_header
from backend.app.core.config import get_settings
from backend.app.knowledge.missing_input import (
    MissingInputApprove,
    MissingInputEdit,
    MissingInputService,
)
from backend.app.models.application_answer import CandidateEvidence
from backend.app.repositories.candidate_profile import ProfileConflictError
from backend.app.services.application_answer_service import ApplicationAnswerService

QUESTION = "Describe a real API integration failure you personally resolved with the payment gateway."


async def missing(session):
    result = await ApplicationAnswerService(session).generate(
        GenerateRequest(question=QUESTION)
    )
    await session.commit()
    assert (
        result.status == "needs_input"
        and result.answer is None
        and result.missing_input_id
    )
    return result


async def test_unknown_question_is_durable_and_deduplicated(db_session, phase2_profile):
    first = await missing(db_session)
    second = await missing(db_session)
    assert first.missing_input_id == second.missing_input_id
    items = await MissingInputService(db_session).list()
    assert len(items) == 1 and items[0]["question"] == QUESTION
    assert items[0]["status"] == "needs_input" and not items[0]["stale"]
    assert items[0]["missing_information"] and items[0]["reason"]


async def test_draft_never_resolves_until_separate_approval_and_edits_invalidate(
    db_session, phase2_profile
):
    request = await missing(db_session)
    service = MissingInputService(db_session)
    draft = await service.edit(
        request.missing_input_id,
        MissingInputEdit(
            expected_version=1,
            answer="The gateway returned HTTP 429; I added bounded retry for idempotent GETs.",
            evidence_note="My fictional incident notes reviewed by me.",
        ),
    )
    assert draft["status"] == "draft" and draft["version"] == 2
    assert (await missing(db_session)).answer is None
    approved = await service.approve(
        request.missing_input_id,
        MissingInputApprove(
            expected_version=2,
            expected_profile_version=phase2_profile.version,
            factual_confirmation=True,
        ),
    )
    assert approved["status"] == "approved" and approved["draft_id"]
    resolved = await ApplicationAnswerService(db_session).generate(
        GenerateRequest(question=QUESTION)
    )
    assert (
        resolved.answer == draft["answer"]
        and resolved.source == "owner_approved_exact_context"
    )
    assert not (await db_session.scalars(select(CandidateEvidence))).all()
    edited = await service.edit(
        request.missing_input_id,
        MissingInputEdit(
            expected_version=3,
            answer="Corrected incident details",
            evidence_note="Correction",
        ),
    )
    assert edited["version"] == 4 and edited["status"] == "draft"
    assert (await missing(db_session)).answer is None
    assert len(await service.history(request.missing_input_id)) == 3
    with pytest.raises(ProfileConflictError, match="version_conflict"):
        await service.edit(
            request.missing_input_id,
            MissingInputEdit(expected_version=3, answer="Lost edit"),
        )


@pytest.mark.parametrize("change", ["profile", "evidence"])
async def test_source_changes_make_exact_approvals_stale(
    db_session, phase2_profile, change
):
    request = await missing(db_session)
    service = MissingInputService(db_session)
    await service.edit(
        request.missing_input_id,
        MissingInputEdit(
            expected_version=1,
            answer="Fictional approved incident",
            evidence_note="Owner evidence",
        ),
    )
    await service.approve(
        request.missing_input_id,
        MissingInputApprove(
            expected_version=2,
            expected_profile_version=phase2_profile.version,
            factual_confirmation=True,
        ),
    )
    if change == "profile":
        phase2_profile.version += 1
    else:
        db_session.add(
            CandidateEvidence(
                candidate_profile_id=phase2_profile.id,
                evidence_type="other",
                title="Correction",
                content="Changed approved evidence",
                user_confirmed=True,
            )
        )
    await db_session.commit()
    value = await service.read(request.missing_input_id)
    assert value["stale"] and value["effective_status"] == "review_required"
    assert (await missing(db_session)).answer is None


@pytest.mark.parametrize(
    "question",
    ["Your password", "Enter verification code", "Passport number", "Your religion"],
)
async def test_sensitive_questions_never_retained(db_session, phase2_profile, question):
    result = await ApplicationAnswerService(db_session).generate(
        GenerateRequest(question=question)
    )
    assert not result.missing_input_id
    assert not (await MissingInputService(db_session).list())


async def test_missing_api_auth_concurrency_and_exact_owner_approval(
    async_client, phase2_profile, phase2_auth, monkeypatch
):
    path = "/api/v1/application-answers/missing"
    assert (await async_client.get(path)).status_code == 401
    generated = await async_client.post(
        "/api/v1/application-answers/generate",
        headers=phase2_auth,
        json={"question": QUESTION},
    )
    assert generated.status_code == 200
    request_id = generated.json()["missing_input_id"]
    listing = await async_client.get(path, headers=phase2_auth)
    assert (
        listing.headers["cache-control"] == "no-store"
        and len(listing.json()["requests"]) == 1
    )
    edit = await async_client.patch(
        path + "/" + request_id,
        headers=phase2_auth,
        json={
            "expected_version": 1,
            "answer": "A factual answer",
            "evidence_note": "Actual incident evidence",
        },
    )
    assert edit.status_code == 200
    assert (
        await async_client.patch(
            path + "/" + request_id,
            headers=phase2_auth,
            json={"expected_version": 1, "answer": "Racing edit"},
        )
    ).status_code == 409
    monkeypatch.setenv(
        "BROWSER_OWNER_APPROVAL_KEY", "fictional-owner-key-32-characters-long"
    )
    get_settings.cache_clear()
    approval_path = path + "/" + request_id + "/approve"
    data = {
        "expected_version": 2,
        "expected_profile_version": phase2_profile.version,
        "factual_confirmation": True,
    }
    assert (
        await async_client.post(approval_path, headers=phase2_auth, json=data)
    ).status_code == 403
    body = json.dumps(data).encode()
    header = approval_header(
        "fictional-owner-key-32-characters-long",
        approval_path,
        body,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    response = await async_client.post(
        approval_path,
        headers={
            **phase2_auth,
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": header,
        },
        content=body,
    )
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert (
        await async_client.get(
            path + "/" + request_id + "/history", headers=phase2_auth
        )
    ).json()["history"]
    get_settings.cache_clear()
