import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google.genai import errors
from sqlalchemy import select

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION
from backend.app.ai.provider_factory import create_provider
from backend.app.ai.providers.gemini import GeminiProvider, retry_after_seconds
from backend.app.ai.schemas import EvidenceReference, ModelAnswer, SupportedClaim
from backend.app.ai.usage import LLMUsageManager
from backend.app.db.session import get_session_factory
from backend.app.models.application_answer import LLMMonthlyUsage
from backend.tests.phase2a_fakes import FakeProvider


def model_content():
    ref = EvidenceReference(source_type="verified_project", source_id="fictional-id")
    return ModelAnswer(answer="I built an API.", evidence_references=[ref], claims=[SupportedClaim(text="I built an API.", source=ref, quote="I built an API.")])


@pytest.mark.asyncio
async def test_current_gemini_structured_api(phase2_settings):
    content = model_content()
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=SimpleNamespace(text=content.model_dump_json(), usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=20)))))
    result = await GeminiProvider(phase2_settings, client).generate_structured_answer("Describe work", {}, {"style_instruction": "technical", "max_characters": 100})
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == phase2_settings.LLM_MODEL
    assert kwargs["config"].response_schema is ModelAnswer
    assert kwargs["config"].system_instruction == SYSTEM_INSTRUCTION
    assert not kwargs["config"].tools
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 20


@pytest.mark.asyncio
async def test_invalid_structured_response_and_unknown_usage(phase2_settings):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=SimpleNamespace(text='{"answer": "invented"}', usage_metadata=None))))
    with pytest.raises(ProviderError, match="invalid_structured_response") as error:
        await GeminiProvider(phase2_settings, client).generate_structured_answer("question", {}, {"style_instruction": "concise", "max_characters": 100})
    assert error.value.usage.input_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(429, "rate_limited"), (403, "provider_authentication"), (503, "provider_error"), (404, "model_unavailable")])
async def test_sdk_error_classification(phase2_settings, status, code):
    response = httpx.Response(status, headers={"retry-after": "60"})
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(side_effect=errors.APIError(status, {"error": {"message": "sensitive-provider-message"}}, response))))
    with pytest.raises(ProviderError) as error:
        await GeminiProvider(phase2_settings, client).generate_structured_answer("question", {}, {"style_instruction": "concise", "max_characters": 100})
    assert error.value.code == code and error.value.retry_after == 60
    assert "sensitive" not in str(error.value)


@pytest.mark.asyncio
async def test_timeout(phase2_settings):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(side_effect=httpx.ReadTimeout("private content"))))
    with pytest.raises(ProviderError, match="timeout"):
        await GeminiProvider(phase2_settings, client).generate_structured_answer("question", {}, {"style_instruction": "concise", "max_characters": 100})


def test_factory_missing_keys_and_provider(phase2_settings):
    phase2_settings.GEMINI_API_KEY = None
    with pytest.raises(ProviderError, match="llm_not_configured"):
        create_provider(phase2_settings)
    phase2_settings.LLM_PROVIDER = "unsupported"
    with pytest.raises(ProviderError, match="unsupported_provider"):
        create_provider(phase2_settings)


@pytest.mark.asyncio
async def test_atomic_monthly_cap_and_durable_reservations(db_session, phase2_settings):
    phase2_settings.LLM_MONTHLY_MAX_REQUESTS = 1
    manager = LLMUsageManager(get_session_factory(), phase2_settings)
    await manager.reserve()
    with pytest.raises(ProviderError, match="monthly_request_limit"):
        await manager.reserve()
    await db_session.rollback()
    async with get_session_factory()() as session:
        row = (await session.scalars(select(LLMMonthlyUsage))).one()
        assert row.requests == 1


@pytest.mark.asyncio
async def test_bounded_retries_count_every_attempt(phase2_settings):
    manager = LLMUsageManager(get_session_factory(), phase2_settings)
    provider = FakeProvider(error=ProviderError("provider_error", transient=True))
    with pytest.raises(ProviderError):
        await manager.generate(provider, "question", {}, {})
    assert len(provider.calls) == 2
    async with get_session_factory()() as session:
        assert (await session.scalars(select(LLMMonthlyUsage))).one().requests == 2


@pytest.mark.asyncio
async def test_zero_limit_and_no_retry_for_429(phase2_settings):
    manager = LLMUsageManager(get_session_factory(), phase2_settings)
    provider = FakeProvider(error=ProviderError("rate_limited", retry_after=3600))
    with pytest.raises(ProviderError, match="rate_limited"):
        await manager.generate(provider, "question", {}, {})
    assert len(provider.calls) == 1
    phase2_settings.LLM_MONTHLY_MAX_REQUESTS = 0
    with pytest.raises(ProviderError, match="monthly_request_limit"):
        await manager.generate(provider, "question", {}, {})
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_concurrency_and_overall_deadline(phase2_settings):
    phase2_settings.LLM_MAX_CONCURRENCY = 1
    phase2_settings.LLM_TIMEOUT_SECONDS = 0.05
    active = 0
    maximum = 0
    class SlowProvider:
        async def generate_structured_answer(self, *args):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(1)
            finally:
                active -= 1
    manager = LLMUsageManager(get_session_factory(), phase2_settings)
    results = await asyncio.gather(*(manager.generate(SlowProvider(), "q", {}, {}) for _ in range(3)), return_exceptions=True)
    assert maximum == 1 and all(isinstance(r, ProviderError) and r.code == "timeout" for r in results)


def test_retry_after_http_date():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    response = httpx.Response(429, headers={"retry-after": format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60))})
    assert 58 <= retry_after_seconds(response) <= 60
    assert retry_after_seconds(httpx.Response(429, headers={"retry-after": "invalid"})) is None


@pytest.mark.asyncio
async def test_rate_limit_cooldown_blocks_later_requests_across_managers(phase2_settings):
    first = LLMUsageManager(get_session_factory(), phase2_settings)
    provider = FakeProvider(error=ProviderError("rate_limited", retry_after=60))
    with pytest.raises(ProviderError, match="rate_limited"):
        await first.generate(provider, "q", {}, {})
    second = LLMUsageManager(get_session_factory(), phase2_settings)
    with pytest.raises(ProviderError, match="rate_limited") as error:
        await second.generate(provider, "q", {}, {})
    assert len(provider.calls) == 1 and error.value.retry_after > 0 and not error.value.attempted
    async with get_session_factory()() as session:
        row = (await session.scalars(select(LLMMonthlyUsage))).one()
        assert row.requests == 1 and row.cooldown_until is not None


@pytest.mark.asyncio
async def test_prior_month_cooldown_does_not_reset_on_month_boundary(phase2_settings):
    from datetime import datetime, timedelta, timezone
    async with get_session_factory()() as session:
        session.add(LLMMonthlyUsage(provider="gemini", month="2000-01", requests=1,
                                    cooldown_until=datetime.now(timezone.utc) + timedelta(seconds=60)))
        await session.commit()
    with pytest.raises(ProviderError, match="rate_limited"):
        await LLMUsageManager(get_session_factory(), phase2_settings).reserve()


def test_nonfinite_retry_after_ignored():
    assert retry_after_seconds(httpx.Response(429, headers={"retry-after": "inf"})) is None


@pytest.mark.asyncio
async def test_enablement_budget_and_key_do_not_authorize_candidate_transfer(phase2_settings):
    phase2_settings.GEMINI_CANDIDATE_DATA_AUTHORIZED = False
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock()))
    with pytest.raises(ProviderError, match="candidate_cloud_authorization_required"):
        create_provider(phase2_settings)
    with pytest.raises(ProviderError, match="candidate_cloud_authorization_required"):
        await GeminiProvider(phase2_settings, client).generate_structured_answer(
            "Describe a project", {"evidence": []}, {})
    client.models.generate_content.assert_not_called()
