"""Prepared provider protocol tests: injected transport only; no live model requests."""
import asyncio
import json

import httpx
import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.provider_factory import configured_model, create_provider
from backend.app.ai.providers.ollama import OllamaProvider
from backend.app.core.config import Settings
from backend.scripts.phase1.ollama_evaluate import CONTEXT

ANSWER = CONTEXT["evidence"][0]["facts"]["description"]

MODEL = "fictional-local:fixture"
INSTRUCTIONS = {"style_instruction": "concise", "max_characters": 500}


def make_settings(**kwargs):
    return Settings(_env_file=None, **{
        "LLM_PROVIDER": "ollama", "OLLAMA_MODEL": MODEL,
        "OLLAMA_GENERATION_AUTHORIZED": True, "LLM_TIMEOUT_SECONDS": 5.0, **kwargs,
    })


def envelope(**changes):
    return {"model": MODEL, "message": {"role": "assistant", "content": json.dumps({"answer": ANSWER})},
            "done": True, "done_reason": "stop", "prompt_eval_count": 42, "eval_count": 88, **changes}


@pytest.mark.parametrize("endpoint", [
    "https://remote.ollama.example:11434", "http://127.0.0.1:11434" + "@external.example",
    "http://127.0.0.1:11434.external.example", "http://localhost:11434",
    "http://127.0.0.1:11434/remote", "http://127.0.0.1:11434?target=external",
    "http://127.0.0.1:11434#fragment", "http://127.0.0.1:11435", "http://[::1]:11434",
])
def test_ollama_rejects_non_exact_loopback_origin(endpoint):
    with pytest.raises(ProviderError, match="ollama_endpoint_must_be_loopback"):
        OllamaProvider(make_settings(), endpoint=endpoint)


async def call_response(data, expected_error=None, status=200):
    async def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        body = json.loads(request.content)
        assert body["tools"] == [] and body["stream"] is False
        assert body["format"]["additionalProperties"] is False
        assert body["options"]["num_ctx"] == 1024
        assert "Authorization" not in request.headers
        return httpx.Response(status, json=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(make_settings(), client=client)
        if expected_error:
            with pytest.raises(ProviderError, match=expected_error):
                await provider.generate_structured_answer("Fictional question", CONTEXT, INSTRUCTIONS)
        else:
            return await provider.generate_structured_answer("Fictional question", CONTEXT, INSTRUCTIONS)


async def test_ollama_parses_valid_structured_response():
    result = await call_response(envelope())
    assert result.content.answer == ANSWER
    assert (result.usage.input_tokens, result.usage.output_tokens) == (42, 88)


async def test_ollama_rejects_malformed_content():
    await call_response(envelope(message={"role": "assistant", "content": "not-json"}), "invalid_structured_response")


@pytest.mark.parametrize("data", [
    [], {"message": []}, envelope(done=False), envelope(model="another-model"),
    envelope(done_reason="length"), envelope(prompt_eval_count=-1), envelope(eval_count=True),
])
async def test_invalid_terminal_metadata_is_rejected(data):
    await call_response(data, "invalid_provider_response")


async def test_unexpected_tools_never_become_answers():
    await call_response(envelope(message={"role": "assistant", "content": json.dumps({"answer": ANSWER}),
        "tool_calls": [{"function": {"name": "execute_sql"}}]}), "provider_tool_use_denied")


async def test_generation_requires_explicit_authorization_before_network():
    settings = make_settings(OLLAMA_GENERATION_AUTHORIZED=False)
    with pytest.raises(ProviderError, match="provider_execution_not_authorized"):
        create_provider(settings)
    called = []
    async def handler(request):
        called.append(request)
        return httpx.Response(200, json=envelope())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="provider_execution_not_authorized"):
            await OllamaProvider(settings, client).generate_structured_answer("Fictional", CONTEXT, INSTRUCTIONS)
    assert called == []
    assert Settings(_env_file=None).OLLAMA_GENERATION_AUTHORIZED is False


def test_no_implicit_or_cloud_model_selection():
    with pytest.raises(ProviderError, match="explicit_model_required"):
        OllamaProvider(make_settings(OLLAMA_MODEL=None))
    with pytest.raises(ProviderError, match="cloud_model_forbidden"):
        OllamaProvider(make_settings(OLLAMA_MODEL="fictional:cloud"))


async def test_redirects_are_not_followed_even_with_redirect_enabled_injected_client():
    requests = []
    async def handler(request):
        requests.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://external.example/api/chat"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(ProviderError, match="provider_redirect_denied"):
            await OllamaProvider(make_settings(), client).generate_structured_answer("Fictional", CONTEXT, INSTRUCTIONS)
    assert requests == ["http://127.0.0.1:11434/api/chat"]


async def test_response_body_is_bounded():
    async def handler(request):
        return httpx.Response(200, content=b"x" * 65537)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="provider_output_size"):
            await OllamaProvider(make_settings(), client).generate_structured_answer("Fictional", CONTEXT, INSTRUCTIONS)


async def test_overall_deadline_bounds_slow_stream_without_retries():
    calls = []
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(2)
            yield b"{}"
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Slow())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="timeout"):
            await OllamaProvider(make_settings(LLM_TIMEOUT_SECONDS=1), client).generate_structured_answer("Fictional", CONTEXT, INSTRUCTIONS)
    assert len(calls) == 1


async def test_missing_model_is_reported_without_fallback():
    await call_response({}, "model_unavailable", status=404)


@pytest.mark.parametrize("settings,expected", [
    (make_settings(), MODEL),
    (Settings(_env_file=None, LLM_PROVIDER="agy", AGY_MODEL="fictional-agy-high"), "fictional-agy-high"),
    (Settings(_env_file=None, LLM_PROVIDER="gemini", LLM_MODEL="gemini-fictional"), "gemini-fictional"),
])
def test_model_provenance_uses_selected_provider_model(settings, expected):
    assert configured_model(settings) == expected
