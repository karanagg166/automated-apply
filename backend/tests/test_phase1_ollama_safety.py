"""Deterministic failure and concurrency checks; live runs use ollama_evaluate.py."""

import asyncio
import json

import httpx
import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.provider_factory import create_provider
from backend.app.ai.providers.ollama import (
    MAX_OUTPUT_TOKENS,
    REQUEST_INSTRUCTION,
    OllamaProvider,
)
from backend.app.ai.usage import LLMUsageManager
from backend.app.ai.validation import validate_grounding
from backend.app.db.session import get_session_factory
from backend.scripts.phase1.ollama_evaluate import CONTEXT, REFERENCE
from backend.tests.test_phase1_ollama_provider import (
    INSTRUCTIONS,
    envelope,
    make_settings,
)


@pytest.mark.parametrize("model", ["qwen:cloud", "qwen:1b-cloud", "cloud-model:1b", "qwen:cloud-v2"])
def test_cloud_variants_never_reach_transport(model):
    with pytest.raises(ProviderError, match="cloud_model_forbidden"):
        create_provider(make_settings(OLLAMA_MODEL=model))


async def test_local_bounds_and_prompt_separation():
    async def handler(request):
        body = json.loads(request.content)
        assert body["keep_alive"] == 0
        assert body["options"] == {
            "num_ctx": 2048, "num_thread": 2, "num_predict": MAX_OUTPUT_TOKENS,
            "temperature": 0, "seed": 0,
        }
        assert body["tools"] == []
        assert "INJECTION_SENTINEL" not in body["messages"][0]["content"]
        wire = json.loads(body["messages"][-1]["content"].removeprefix(REQUEST_INSTRUCTION))
        assert wire["candidate_facts"]["evidence"][0]["facts"]["note"] == "INJECTION_SENTINEL"
        return httpx.Response(200, json=envelope())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await OllamaProvider(make_settings(LLM_MAX_OUTPUT_TOKENS=8192), client).generate_structured_answer(
            "Fictional", {"evidence": [{"reference": REFERENCE, "facts": {"note": "INJECTION_SENTINEL"}}]}, INSTRUCTIONS,
        )


@pytest.mark.parametrize("kind,error", [
    ("transport", "connection_error"), ("timeout", "timeout"),
    ("invalid_json", "invalid_provider_response"), ("excess_tokens", "provider_output_size"),
    ("extra_fields", "invalid_structured_response"), ("too_many_words", "output_length_exceeded"),
    ("too_many_characters", "output_length_exceeded"),
])
async def test_failures_are_sanitized_without_provider_retries(kind, error):
    calls = []

    async def handler(request):
        calls.append(request)
        if kind == "transport":
            raise httpx.ConnectError("private fixture value")
        if kind == "timeout":
            raise httpx.ReadTimeout("private fixture value")
        if kind == "invalid_json":
            return httpx.Response(200, content=b"not JSON")
        data = envelope()
        if kind == "excess_tokens":
            data["eval_count"] = MAX_OUTPUT_TOKENS + 1
        if kind == "extra_fields":
            content = json.loads(data["message"]["content"])
            content["execute_shell"] = "private fixture value"
            data["message"]["content"] = json.dumps(content)
        return httpx.Response(200, json=data)

    instructions = {**INSTRUCTIONS}
    if kind == "too_many_words":
        instructions["max_words"] = 1
    if kind == "too_many_characters":
        instructions["max_characters"] = 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match=error) as caught:
            await OllamaProvider(make_settings(), client).generate_structured_answer("Fictional", {}, instructions)
    assert "private fixture" not in str(caught.value)
    assert len(calls) == 1


async def test_whole_input_limit_prevents_network():
    async def handler(request):
        pytest.fail("Oversized input reached the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="input_size_exceeded"):
            await OllamaProvider(make_settings(LLM_MAX_INPUT_CHARS=1000), client).generate_structured_answer(
                "Fictional", {}, INSTRUCTIONS,
            )


async def test_encoded_responses_are_rejected_before_decompression():
    consumed = False

    class Encoded(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            consumed = True
            yield b"untrusted compressed data"

    async def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Encoded())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="provider_encoding_denied"):
            await OllamaProvider(make_settings(), client).generate_structured_answer("q", {}, INSTRUCTIONS)
    assert not consumed


async def test_missing_terminal_reason_is_not_assumed_success():
    data = envelope()
    data.pop("done_reason")

    async def handler(request):
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="invalid_provider_response"):
            await OllamaProvider(make_settings(), client).generate_structured_answer("q", {}, INSTRUCTIONS)


async def test_single_generation_across_provider_instances_and_cancellation():
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    active = maximum = calls = 0

    async def handler(request):
        nonlocal active, maximum, calls
        active += 1
        calls += 1
        maximum = max(maximum, active)
        entered.set()
        try:
            await release.wait()
            return httpx.Response(200, json=envelope())
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = OllamaProvider(make_settings(), client)
        second = OllamaProvider(make_settings(), client)
        running = asyncio.create_task(first.generate_structured_answer("q", {}, INSTRUCTIONS))
        await entered.wait()
        waiter = asyncio.create_task(second.generate_structured_answer("q", {}, INSTRUCTIONS))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert calls == 1
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert cancelled.is_set() and active == 0
        release.set()
        await asyncio.gather(*(p.generate_structured_answer("q", {}, INSTRUCTIONS) for p in (first, second)))
    assert calls == 3 and maximum == 1


async def test_queued_request_deadline_does_not_interrupt_active_generation():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=envelope())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        running = asyncio.create_task(OllamaProvider(make_settings(), client).generate_structured_answer("q", {}, INSTRUCTIONS))
        await entered.wait()
        try:
            with pytest.raises(ProviderError, match="timeout"):
                await OllamaProvider(make_settings(LLM_TIMEOUT_SECONDS=1), client).generate_structured_answer("q", {}, INSTRUCTIONS)
            assert not running.done()
        finally:
            release.set()
            await running


async def test_existing_usage_manager_with_one_slot_does_not_deadlock():
    async def handler(request):
        return httpx.Response(200, json=envelope())

    config = make_settings(LLM_MAX_CONCURRENCY=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(config, client)
        result = await LLMUsageManager(get_session_factory(), config).generate(provider, "q", {}, INSTRUCTIONS)
        assert result.content.answer


def test_existing_grounding_rejects_invented_project_metrics_and_bad_citations():
    from backend.app.ai.schemas import ModelAnswer

    def content(answer, quote, reference=REFERENCE):
        return ModelAnswer.model_validate({
            "answer": answer, "evidence_references": [reference],
            "claims": [{"text": answer, "quote": quote, "source": reference}],
        })

    quote = "My project is ClinicDemo."
    assert validate_grounding(content(quote, quote), CONTEXT["evidence"], 1000, 50) is None
    assert validate_grounding(content("My project has 42 million users.", quote), CONTEXT["evidence"], 1000, 50)
    assert validate_grounding(content(quote, "Imaginary approved evidence"), CONTEXT["evidence"], 1000, 50) == "unsupported_claim"
    assert validate_grounding(content(quote, quote, {**REFERENCE, "source_id": "unknown"}), CONTEXT["evidence"], 1000, 50) == "invalid_evidence_reference"
