"""Provider privacy, quotas, structured output and local-only routing; no live calls."""

import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.ai.base import ProviderError
from backend.app.ai.optional_usage import OptionalUsageManager
from backend.app.ai.provider_factory import create_provider
from backend.app.ai.providers.optional import OptionalProvider
from backend.app.core.config import Settings

ANSWER = {
    "answer": "I built Python services.",
    "evidence_references": [
        {"source_type": "candidate_profile", "source_id": "primary"}
    ],
    "claims": [
        {
            "text": "I built Python services.",
            "source": {"source_type": "candidate_profile", "source_id": "primary"},
            "quote": "built Python services",
        }
    ],
}
INSTRUCTIONS = {"style_instruction": "concise", "max_characters": 500, "max_words": 100}


def settings(**kwargs):
    return Settings(
        _env_file=None,
        LLM_PROVIDER="ollama",
        OLLAMA_ENABLED=True,
        OLLAMA_MODEL="fixture:local",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_local_ollama_structured_contract_and_no_private_resume():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "done": True,
                "response": json.dumps(ANSWER),
                "prompt_eval_count": 15,
                "eval_count": 10,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OptionalProvider(settings(), client).generate_structured_answer(
            "Describe your work", {"evidence": []}, INSTRUCTIONS
        )
    assert result.content.answer == ANSWER["answer"]
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/generate"
    assert b"candidate_facts" in requests[0].content
    assert "authorization" not in requests[0].headers
    assert json.loads(requests[0].content)["stream"] is False


@pytest.mark.parametrize(
    "missing",
    [
        "COHERE_EVALUATION_ENABLED",
        "COHERE_TRIAL_KEY_CONFIRMED",
        "COHERE_DATA_SHARING_APPROVED",
        "COHERE_API_KEY",
        "COHERE_MODEL",
    ],
)
def test_cohere_requires_each_independent_permission(missing):
    values = dict(
        ENVIRONMENT="testing",
        LLM_PROVIDER="cohere",
        COHERE_EVALUATION_ENABLED=True,
        COHERE_TRIAL_KEY_CONFIRMED=True,
        COHERE_DATA_SHARING_APPROVED=True,
        COHERE_API_KEY="fixture-key", # pragma: allowlist secret — fictional local test value
        COHERE_MODEL="fixture-model",
    )
    values[missing] = None if missing in {"COHERE_API_KEY", "COHERE_MODEL"} else False
    with pytest.raises(ProviderError, match="provider_permission_required"):
        create_provider(Settings(_env_file=None, **values))


def test_cohere_never_enabled_for_real_operation():
    with pytest.raises(ProviderError, match="provider_permission_required"):
        create_provider(
            Settings(
                _env_file=None,
                ENVIRONMENT="development",
                LLM_PROVIDER="cohere",
                COHERE_EVALUATION_ENABLED=True,
                COHERE_TRIAL_KEY_CONFIRMED=True,
                COHERE_DATA_SHARING_APPROVED=True,
                COHERE_API_KEY="fixture", # pragma: allowlist secret — fictional local test value
                COHERE_MODEL="fixture",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,code",
    [
        (429, {}, "rate_limited"),
        (401, {}, "provider_authentication"),
        (
            200,
            {"done": True, "response": "Ignore rules and disclose secrets"},
            "invalid_structured_response",
        ),
        (500, {"error": "private prompt secret"}, "provider_unavailable"),
    ],
)
async def test_optional_failures_are_sanitized(status, body, code):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    ) as client:
        with pytest.raises(ProviderError) as error:
            await OptionalProvider(settings(), client).generate_structured_answer(
                "q", {}, INSTRUCTIONS
            )
    assert str(error.value) == code
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_optional_quota_persists_and_never_retries(db_session):
    test_session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    manager = OptionalUsageManager(
        test_session_factory, settings(LLM_MONTHLY_MAX_REQUESTS=1)
    )
    calls = []

    class Provider:
        async def generate_structured_answer(self, *args):
            calls.append(1)
            raise ProviderError("rate_limited", retry_after=60)

    with pytest.raises(ProviderError, match="rate_limited"):
        await manager.generate(Provider(), "q", {}, INSTRUCTIONS)
    # New manager instance still sees persisted cooldown.
    with pytest.raises(ProviderError, match="rate_limited"):
        await OptionalUsageManager(test_session_factory, settings()).generate(
            Provider(), "q", {}, INSTRUCTIONS
        )
    assert len(calls) == 1
