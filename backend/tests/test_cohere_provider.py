"""Realistic Chat V2 envelopes over mocked HTTP; fictional data only."""
import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.app.ai.base import ProviderError
from backend.app.ai.provider_factory import configured_model, create_provider
from backend.app.ai.providers.cohere import CohereProvider
from backend.app.ai.schemas import TokenUsage
from backend.app.ai.usage import LLMUsageManager
from backend.app.core.config import Settings
from backend.app.db.session import get_session_factory
from backend.app.models.application_answer import LLMMonthlyUsage


class CommandFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str


def config(**changes):
    return Settings(_env_file=None, **{
        "LLM_PROVIDER": "cohere", "COHERE_API_KEY": "fictional-evaluation-key",  # pragma: allowlist secret — fictional fixture only
        "COHERE_ENABLED": True, "COHERE_EVALUATION_KEY_CONFIRMED": True, **changes})


def envelope(text='{"intent":"search"}', **updates):
    return {"id": "fictional-response", "finish_reason": "COMPLETE",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        "usage": {"tokens": {"input_tokens": 42, "output_tokens": 7},
                  "billed_units": {"input_tokens": 40, "output_tokens": 7}}, **updates}


@pytest.mark.asyncio
async def test_chat_v2_structured_contract_and_usage(caplog):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=envelope())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = CohereProvider(config(), client)
        value, usage = await provider.json("Classify fictional instructions.", {"text": "Find jobs"}, CommandFixture)
    assert value.intent == "search" and usage == TokenUsage(input_tokens=42, output_tokens=7)
    request = seen[0]
    assert str(request.url) == "https://api.cohere.com/v2/chat"
    body = json.loads(request.content)
    assert body["model"] == "command-a-plus-05-2026" and not body["stream"]
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"]["schema"]["additionalProperties"] is False
    assert "tools" not in body and "JSON" in body["messages"][0]["content"]
    assert "fictional-evaluation-key" not in caplog.text


@pytest.mark.asyncio
async def test_strict_tools_are_separate_from_json_output():
    def handle(request):
        body = json.loads(request.content)
        assert body["strict_tools"] and "response_format" not in body
        return httpx.Response(200, json=envelope(finish_reason="TOOL_CALL", message={
            "role": "assistant", "tool_calls": [{"id": "tool-1", "type": "function",
                "function": {"name": "search_jobs", "arguments": '{"query":"Python"}'}}]}))
    tool = {"type": "function", "function": {"name": "search_jobs", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await CohereProvider(config(), client).chat([{"role": "user", "content": "Find Python jobs"}], tools=[tool])
    assert result.finish_reason == "tool_call"
    assert result.message["tool_calls"][0]["function"]["name"] == "search_jobs"


@pytest.mark.parametrize("settings,error", [
    ({"COHERE_API_KEY": None}, "llm_not_configured"),
    ({"COHERE_ENABLED": False}, "cohere_evaluation_authorization_required"),
    ({"COHERE_EVALUATION_KEY_CONFIRMED": False}, "cohere_evaluation_authorization_required"),
])
def test_configuration_fails_closed(settings, error):
    with pytest.raises(ProviderError, match=error):
        CohereProvider(config(**settings))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(302, "provider_error"), (401, "provider_authentication"),
    (403, "provider_authentication"), (404, "model_unavailable"), (429, "rate_limited"),
    (498, "provider_authentication"), (500, "provider_error")])
async def test_transport_errors_never_retry_or_echo_provider_payload(status, error):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "untrusted sensitive provider message"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            await CohereProvider(config(), client).json("Classify.", {}, CommandFixture)
    assert caught.value.code == error and len(calls) == 1
    assert "sensitive" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,error", [
    (envelope("broken"), "invalid_structured_response"),
    (envelope('{"intent":"search","authorized":true}'), "invalid_structured_response"),
    (envelope(finish_reason="MAX_TOKENS"), "incomplete_generation"),
    (envelope(message={"role": "tool"}), "invalid_structured_response"),
])
async def test_invalid_output_keeps_usage_for_accounting(body, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        with pytest.raises(ProviderError) as caught:
            await CohereProvider(config(), client).json("Classify.", {}, CommandFixture)
    assert caught.value.code == error
    assert caught.value.usage.input_tokens == 42


@pytest.mark.asyncio
async def test_size_limits_and_candidate_privacy_gate():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 140000))) as client:
        provider = CohereProvider(config(), client)
        with pytest.raises(ProviderError, match="provider_response_size"):
            await provider.json("Classify.", {}, CommandFixture)
        with pytest.raises(ProviderError, match="input_limit_exceeded"):
            await provider.json("Classify.", {"text": "x" * 17000}, CommandFixture)
        with pytest.raises(ProviderError, match="candidate_cloud_authorization_required"):
            await provider.generate_structured_answer("Describe a project", {}, {})


@pytest.mark.asyncio
async def test_durable_cohere_monthly_rate_and_token_bounds(db_session):
    manager = LLMUsageManager(get_session_factory(), config())
    month = await manager.reserve()
    with pytest.raises(ProviderError, match="rate_limited"):
        await LLMUsageManager(get_session_factory(), config()).reserve()
    await manager.record_tokens(month, TokenUsage(input_tokens=42, output_tokens=7))
    usage = await db_session.scalar(select(LLMMonthlyUsage))
    assert usage.requests == 1 and usage.input_tokens == 42 and usage.output_tokens == 7
    bounded = LLMUsageManager(get_session_factory(), config(COHERE_MONTHLY_MAX_TOKENS=1))
    with pytest.raises(ProviderError, match="monthly_request_limit"):
        await bounded.reserve()


def test_factory_has_no_cross_provider_fallback():
    assert isinstance(create_provider(config()), CohereProvider)
    assert configured_model(config()) == "command-a-plus-05-2026"


@pytest.mark.asyncio
async def test_actual_v2_tool_argument_json_is_locally_validated():
    from backend.app.agent.tools import definitions
    body = envelope(finish_reason="TOOL_CALL", message={"role": "assistant", "tool_calls": [
        {"id": "tool-search", "type": "function", "function": {"name": "search_jobs", "arguments": '{"filters":{"role":"Python","limit":3}}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        proposals, usage = await CohereProvider(config(), client).propose_tools("Propose a bounded search.", {"command": "Find Python jobs"}, definitions())
    assert proposals[0].name == "search_jobs" and proposals[0].arguments["filters"]["limit"] == 3
    assert usage.input_tokens == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [("submit_application", '{"job_id":"invented"}'),
    ("search_jobs", '{"filters":{"limit":500}}'), ("search_jobs", '{"filters":{},"authorized":true}'),
    ("search_jobs", {}), ("run_sql", '{"sql":"delete everything"}')])
async def test_forged_tool_calls_never_become_executable(name, arguments):
    from backend.app.agent.tools import definitions
    body = envelope(finish_reason="TOOL_CALL", message={"role": "assistant", "tool_calls": [
        {"id": "tool-1", "type": "function", "function": {"name": name, "arguments": arguments}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        with pytest.raises(ProviderError, match="invalid_tool_proposal") as caught:
            await CohereProvider(config(), client).propose_tools("Propose.", {}, definitions())
    assert caught.value.usage.output_tokens == 7


@pytest.mark.asyncio
async def test_timeout_is_bounded_no_retries():
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("Never disclose private token values")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError, match="cohere_transport_error"):
            await CohereProvider(config(), client).json("Classify", {}, CommandFixture)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_command_consent_and_candidate_consent_independent():
    from backend.app.agent.planner import CommandPlanner
    # Injecting a transport here would bypass the runtime consent branch. Use the real factory;
    # conftest forbids all network, so any accidental transmission fails the test immediately.
    settings = config(COHERE_OWNER_TEXT_AUTHORIZED=False)
    result, _ = await CommandPlanner(settings).understand("do that vague thing", {})
    assert result.intent == "clarify"
    settings = config(COHERE_OWNER_TEXT_AUTHORIZED=True, COHERE_CANDIDATE_DATA_AUTHORIZED=False)
    for text in ["Use my resume facts to decide something", "I built a project involving private hospital records", "Contact me at owner@example.org", "Karan graduated from Example University"]:
        result, _ = await CommandPlanner(settings).understand(text, {})
        assert result.intent == "clarify"


def test_every_v2_structured_object_has_required_properties():
    from backend.app.agent.contracts import Understanding
    from backend.app.agent.tools import definitions
    from backend.app.ai.providers.cohere import supported_schema
    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object" and value.get("properties"):
                assert value.get("required")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(supported_schema(Understanding.model_json_schema()))
    visit(supported_schema(definitions()))
