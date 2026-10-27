"""API-owned reads may release; embedded writes and stale evidence may not."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.ai.schemas import GenerateRequest
from backend.app.api.v1.applications import application_service
from backend.app.db.session import get_session_factory
from backend.app.main import app
from backend.app.models.application_answer import ApplicationAnswerDraft
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.phase2a_fakes import FakeProvider


@pytest.mark.asyncio
async def test_provider_result_rejected_if_approved_profile_changes(
    db_session, phase2_profile, phase2_settings
):
    class Changed(FakeProvider):
        async def generate_structured_answer(self, *args):
            result = await super().generate_structured_answer(*args)
            async with get_session_factory()() as session:
                profile = await session.get(CandidateProfile, phase2_profile.id)
                profile.projects = []
                await session.commit()
            return result

    provider = Changed()
    result = await ApplicationAnswerService(
        db_session, phase2_settings, provider, owns_read_transaction=True
    ).generate(
        GenerateRequest(question="Describe a project", rewrite=True, save_draft=True)
    )
    assert (
        result.status == "validation_failed"
        and result.error_code == "generation_context_changed"
    )
    assert result.answer is None and not result.draft_id and len(provider.calls) == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ApplicationAnswerDraft)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_api_owned_generation_never_commits_staged_owner_changes(
    db_session, phase2_profile, phase2_settings
):
    phase2_profile.full_name = "Staged owner change"
    fake = FakeProvider()
    result = await ApplicationAnswerService(
        db_session, phase2_settings, fake, owns_read_transaction=True
    ).generate(GenerateRequest(question="Describe a project", rewrite=True))
    assert (
        result.error_code == "generation_requires_clean_transaction" and not fake.calls
    )
    assert phase2_profile in db_session.dirty
    await db_session.rollback()


@pytest.mark.asyncio
async def test_packet_api_cannot_acknowledge_failed_commit(
    async_client, phase2_auth, application_target, packet_service, monkeypatch
):
    job, _ = application_target
    app.dependency_overrides[application_service] = lambda: packet_service
    monkeypatch.setattr(
        packet_service.session,
        "commit",
        AsyncMock(side_effect=SQLAlchemyError("fictional-disconnect")),
    )
    try:
        response = await async_client.post(
            f"/api/v1/jobs/{job.id}/application-packets",
            headers=phase2_auth,
            json={"idempotency_key": "failed-acknowledgement"},
        )
    finally:
        app.dependency_overrides.pop(application_service, None)
    assert response.status_code == 503 and "fictional-disconnect" not in response.text
    assert response.json()["detail"] == "Application storage unavailable"
