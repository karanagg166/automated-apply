"""Bounded official Chat V2 transport. No SDK retries, provider fallback or tools executed.

Contract verified 2026-10-26: response_format and tools are separate API modes.
Unsupported schema bounds are enforced locally; strict_tools is experimental.
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage

ENDPOINT = "https://api.cohere.com/v2/chat"
UNSUPPORTED = {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "default", "title"}


def supported_schema(value):
    """Remove unsupported constraints, keeping the authoritative Pydantic validator."""
    if isinstance(value, list):
        return [supported_schema(item) for item in value]
    if isinstance(value, dict):
        result = {key: supported_schema(item) for key, item in value.items() if key not in UNSUPPORTED}
        # V2 requires a required property on every structured object, including nested filters.
        # A nullable first property is sufficient; local contracts and filter-patch checks remain authoritative.
        if result.get("type") == "object" and result.get("properties") and not result.get("required"):
            result["required"] = [next(iter(result["properties"]))]
        return result
    return value


@dataclass(frozen=True)
class ChatResult:
    message: dict[str, Any]
    usage: TokenUsage
    finish_reason: str


class CohereProvider:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client
        if not settings.COHERE_API_KEY or not settings.COHERE_MODEL:
            raise ProviderError("llm_not_configured")
        if not settings.COHERE_ENABLED or not settings.COHERE_EVALUATION_KEY_CONFIRMED:
            raise ProviderError("cohere_evaluation_authorization_required")

    async def chat(self, messages, *, schema=None, tools=None):
        if (schema is None) == (tools is None):
            raise ProviderError("cohere_select_one_output_mode")
        body = {"model": self.settings.COHERE_MODEL, "messages": messages, "stream": False,
                "temperature": 0, "max_tokens": self.settings.LLM_MAX_OUTPUT_TOKENS}
        if self.settings.COHERE_MODEL == "command-a-plus-05-2026":
            body["thinking"] = {"type": "disabled"}
        if tools is not None:
            if not tools or len(tools) > 16 or any(not tool["function"]["parameters"].get("required") for tool in tools):
                raise ProviderError("invalid_tool_schema")
            body.update(tools=supported_schema(tools), strict_tools=True, tool_choice="REQUIRED")
        else:
            body["response_format"] = {"type": "json_object", "schema": supported_schema(schema)}
        encoded = json.dumps(body, ensure_ascii=False).encode()
        if len(encoded) > self.settings.LLM_MAX_INPUT_CHARS:
            raise ProviderError("input_limit_exceeded")
        async with asyncio.timeout(self.settings.LLM_TIMEOUT_SECONDS):
            if self.client is not None:
                return await self._send(self.client, encoded)
            async with httpx.AsyncClient(timeout=self.settings.LLM_TIMEOUT_SECONDS, follow_redirects=False,
                                         trust_env=False) as client:
                return await self._send(client, encoded)

    async def _send(self, client, encoded):
        try:
            # Stream even non-streaming JSON to bound memory before buffering an untrusted response.
            async with client.stream("POST", ENDPOINT, content=encoded, headers={
                "Authorization": "Bearer " + self.settings.COHERE_API_KEY.get_secret_value(),
                "Content-Type": "application/json", "X-Client-Name": "automated-apply-evaluation",
            }, follow_redirects=False) as response:
                if response.status_code == 429:
                    raise ProviderError("rate_limited", retry_after=60)
                if response.status_code in {401, 403, 498}:
                    raise ProviderError("provider_authentication")
                if response.status_code == 404:
                    raise ProviderError("model_unavailable")
                if response.status_code != 200:
                    raise ProviderError("provider_error")
                parts, size = [], 0
                async for part in response.aiter_bytes():
                    size += len(part)
                    if size > 131072:
                        raise ProviderError("provider_response_size")
                    parts.append(part)
                payload = json.loads(b"".join(parts))
        except (httpx.HTTPError, TimeoutError):
            raise ProviderError("cohere_transport_error") from None
        except (ValueError, TypeError):
            raise ProviderError("invalid_structured_response") from None
        usage = None
        try:
            raw = payload.get("usage", {}).get("tokens", {})
            usage = TokenUsage.model_validate({"input_tokens": raw.get("input_tokens"),
                                              "output_tokens": raw.get("output_tokens")})
            finish = payload["finish_reason"].lower()
            if finish not in {"complete", "tool_call"}:
                raise ProviderError("incomplete_generation", usage=usage)
            message = payload["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError
            return ChatResult(message, usage, finish)
        except (KeyError, AttributeError, TypeError, ValueError, ValidationError):
            raise ProviderError("invalid_structured_response", usage=usage) from None

    async def json(self, system, data, contract):
        result = await self.chat([
            {"role": "system", "content": system + " Return a JSON object matching the schema."},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ], schema=contract.model_json_schema())
        try:
            if result.message.get("tool_calls"):
                raise ValueError
            content = result.message.get("content", [])
            if len(content) != 1 or content[0].get("type") != "text":
                raise ValueError
            value = contract.model_validate_json(content[0]["text"])
            return value, result.usage
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError("invalid_structured_response", usage=result.usage) from None

    async def generate_structured_answer(self, question, grounded_context, instructions):
        if not self.settings.COHERE_CANDIDATE_DATA_AUTHORIZED:
            raise ProviderError("candidate_cloud_authorization_required")
        value, usage = await self.json(SYSTEM_INSTRUCTION,
            json.loads(build_payload(question, grounded_context, instructions)), ModelAnswer)
        return ProviderAnswer(content=value, usage=usage)

    async def propose_tools(self, system, data, definitions):
        """Parse actual V2 function arguments. Returned proposals carry no execution grant."""
        from backend.app.agent.contracts import ToolCall
        from backend.app.agent.tools import REGISTRY

        result = await self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ], tools=definitions)
        try:
            calls = result.message["tool_calls"]
            if result.finish_reason != "tool_call" or not 1 <= len(calls) <= 16:
                raise ValueError
            proposals, identities = [], set()
            allowed = {d["function"]["name"] for d in definitions}
            for call in calls:
                if call["type"] != "function" or not isinstance(call["id"], str) or call["id"] in identities:
                    raise ValueError
                identities.add(call["id"])
                name, arguments = call["function"]["name"], call["function"]["arguments"]
                if name not in REGISTRY or name not in allowed or not isinstance(arguments, str):
                    raise ValueError
                args = REGISTRY[name].model_validate_json(arguments)
                proposals.append(ToolCall(name=name, arguments=args.model_dump(mode="json")))
            return proposals, result.usage
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ProviderError("invalid_tool_proposal", usage=result.usage) from None
