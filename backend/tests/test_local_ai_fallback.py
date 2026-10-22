"""Local-only fallback retains grounding, budgets, honest provider identity and privacy."""

import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.provider_factory import create_provider
from backend.app.ai.schemas import GenerateRequest
from backend.app.core.config import Settings
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.tests.phase2a_fakes import FakeProvider


@pytest.mark.asyncio
async def test_quota_exhaustion_falls_back_locally_and_labels_actual_model(
    db_session, phase2_profile, phase2_settings, monkeypatch
):
    primary = FakeProvider(error=ProviderError("rate_limited"))
    local = FakeProvider()
    phase2_settings.LLM_LOCAL_FALLBACK_ENABLED = True
    phase2_settings.OLLAMA_ENABLED = True
    phase2_settings.OLLAMA_MODEL = "fictional-local-model"
    seen = []

    def factory(settings):
        seen.append(settings.LLM_PROVIDER)
        assert settings.LLM_PROVIDER == "ollama"
        return local

    monkeypatch.setattr("backend.app.ai.fallback.create_provider", factory)
    result = await ApplicationAnswerService(
        db_session, phase2_settings, primary
    ).generate(GenerateRequest(question="Describe a project you built"))
    assert result.status == "draft_ready", result
    assert result.provider == "ollama" and result.model == "fictional-local-model"
    assert len(primary.calls) == 1 and len(local.calls) == 1 and seen == ["ollama"]
    assert any("local Ollama fallback" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_fallback_never_enables_a_remote_provider(
    db_session, phase2_profile, monkeypatch
):
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="ollama",
        OLLAMA_ENABLED=True,
        OLLAMA_MODEL="fictional-local",
        LLM_LOCAL_FALLBACK_ENABLED=True,
    )
    local = FakeProvider(error=ProviderError("connection_error"))
    result = await ApplicationAnswerService(db_session, settings, local).generate(
        GenerateRequest(question="Describe a project you built")
    )
    assert result.status == "provider_unavailable" and len(local.calls) == 1
    assert result.provider == "ollama"


def test_gemini_requires_independent_enablement_and_approved_budget():
    values = dict(
        _env_file=None, GEMINI_API_KEY="fictional-key", LLM_MODEL="gemini-test"  # pragma: allowlist secret — fictional fixture only
    )
    with pytest.raises(ProviderError, match="provider_permission_required"):
        create_provider(Settings(**values))
    with pytest.raises(ProviderError, match="provider_permission_required"):
        create_provider(
            Settings(**values, GEMINI_ENABLED=True, GEMINI_APPROVED_MONTHLY_REQUESTS=0)
        )


@pytest.mark.asyncio
async def test_failed_local_fallback_reports_the_actual_provider_without_an_answer(
    db_session, phase2_profile, phase2_settings, monkeypatch
):
    phase2_settings.LLM_LOCAL_FALLBACK_ENABLED = True
    phase2_settings.OLLAMA_ENABLED = True
    phase2_settings.OLLAMA_MODEL = "fictional-local-model"
    local = FakeProvider(error=ProviderError("local_model_unverified"))
    monkeypatch.setattr(
        "backend.app.ai.fallback.create_provider", lambda settings: local
    )
    result = await ApplicationAnswerService(
        db_session, phase2_settings, FakeProvider(error=ProviderError("rate_limited"))
    ).generate(GenerateRequest(question="Describe a project you built"))
    assert result.answer is None
    assert result.provider == "ollama" and result.model == "fictional-local-model"
    assert result.error_code == "local_model_unverified"
