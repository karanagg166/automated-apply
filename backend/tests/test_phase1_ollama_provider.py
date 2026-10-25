"""Isolated unit tests for prepared Ollama provider; zero external calls or live quota."""
import json

import httpx
import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.providers.ollama import OllamaProvider
from backend.app.core.config import Settings
from backend.tests.test_phase1_local_agent import model_answer

DUMMY_INSTRUCTIONS = {"style_instruction": "concise", "max_characters": 500}


def make_settings(**kwargs):
    return Settings(
        _env_file=None,
        LLM_PROVIDER="ollama",
        OLLAMA_MODEL="qwen2.5:1.5b-instruct",
        LLM_TIMEOUT_SECONDS=5.0,
        **kwargs
    )


@pytest.mark.asyncio
async def test_ollama_rejects_non_loopback_endpoint():
    settings = make_settings()
    with pytest.raises(ProviderError, match="ollama_endpoint_must_be_loopback"):
        OllamaProvider(settings, endpoint="https://remote.ollama.example:11434")


@pytest.mark.asyncio
async def test_ollama_parses_valid_structured_response():
    valid_answer = model_answer()
    response_data = {
        "model": "qwen2.5:1.5b-instruct",
        "message": {"role": "assistant", "content": json.dumps(valid_answer)},
        "prompt_eval_count": 42,
        "eval_count": 88,
        "done": True,
    }

    async def fake_handler(request):
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["format"]["type"] == "object"
        assert body["options"]["num_ctx"] == 2048
        return httpx.Response(200, json=response_data)

    transport = httpx.MockTransport(fake_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(make_settings(), client=client)
        result = await provider.generate_structured_answer(
            "What is your role?",
            {"candidate_evidence": [{"id": "ev-1", "description": "Experienced backend dev"}]},
            DUMMY_INSTRUCTIONS
        )
        assert result.content.answer == valid_answer["answer"]
        assert result.usage.input_tokens == 42
        assert result.usage.output_tokens == 88


@pytest.mark.asyncio
async def test_ollama_rejects_malformed_json_response():
    async def fake_handler(request):
        return httpx.Response(200, json={"message": {"content": "not-valid-json"}})

    transport = httpx.MockTransport(fake_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(make_settings(), client=client)
        with pytest.raises(ProviderError, match="invalid_structured_response"):
            await provider.generate_structured_answer("question", {}, DUMMY_INSTRUCTIONS)


@pytest.mark.asyncio
async def test_ollama_model_not_found():
    async def fake_handler(request):
        return httpx.Response(404, json={"error": "model 'nonexistent' not found"})

    transport = httpx.MockTransport(fake_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(make_settings(), client=client)
        with pytest.raises(ProviderError, match="model_unavailable"):
            await provider.generate_structured_answer("question", {}, DUMMY_INSTRUCTIONS)


@pytest.mark.asyncio
async def test_ollama_timeout():
    async def fake_handler(request):
        raise httpx.TimeoutException("Read timed out")

    transport = httpx.MockTransport(fake_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(make_settings(), client=client)
        with pytest.raises(ProviderError, match="timeout"):
            await provider.generate_structured_answer("question", {}, DUMMY_INSTRUCTIONS)
