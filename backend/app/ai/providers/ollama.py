"""Prepared, opt-in local transport. Daemon/model isolation still needs live review.

No installation, model pull, fallback or tool execution is performed here.
Loopback HTTP does not by itself prove an Ollama daemon is operating offline.
"""
import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
MAX_RESPONSE_BYTES = 65536


class OllamaProvider:
    def __init__(self, settings: Any, client: httpx.AsyncClient | None = None,
                 endpoint: str = DEFAULT_OLLAMA_ENDPOINT):
        # Exact origin: prefix checks accept userinfo such as 127.0.0.1:11434@host.
        if endpoint not in {DEFAULT_OLLAMA_ENDPOINT, DEFAULT_OLLAMA_ENDPOINT + "/"}:
            raise ProviderError("ollama_endpoint_must_be_loopback")
        self.settings, self.client, self.endpoint = settings, client, DEFAULT_OLLAMA_ENDPOINT
        self.model = settings.OLLAMA_MODEL
        if not self.model:
            raise ProviderError("explicit_model_required")
        if "cloud" in self.model.casefold().split(":")[-1].split("-"):
            raise ProviderError("cloud_model_forbidden")

    async def generate_structured_answer(self, question, grounded_context, instructions):
        if not self.settings.OLLAMA_GENERATION_AUTHORIZED or self.settings.LLM_PROVIDER != "ollama":
            raise ProviderError("provider_execution_not_authorized")
        payload = build_payload(question, grounded_context, instructions)
        if len(payload) > self.settings.LLM_MAX_INPUT_CHARS:
            raise ProviderError("input_size_exceeded")
        body = {"model": self.model,
                "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION},
                             {"role": "user", "content": payload}],
                "format": ModelAnswer.model_json_schema(), "tools": [], "stream": False,
                "options": {"temperature": 0.2, "num_ctx": 2048,
                            "num_predict": self.settings.LLM_MAX_OUTPUT_TOKENS}}
        try:
            # Overall deadline also bounds a server that drips bytes below read timeouts.
            async with asyncio.timeout(self.settings.LLM_TIMEOUT_SECONDS):
                if self.client is not None:
                    raw = await self._request(self.client, body)
                else:
                    async with httpx.AsyncClient(trust_env=False) as client:
                        raw = await self._request(client, body)
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
                raise ValueError
            message = data["message"]
            if message.get("tool_calls") or data.get("tool_calls"):
                raise ProviderError("provider_tool_use_denied")
            if (data.get("done") is not True or data.get("model") != self.model
                    or message.get("role") != "assistant" or data.get("done_reason", "stop") != "stop"):
                raise ValueError
            counts = [data.get(key) for key in ("prompt_eval_count", "eval_count")]
            if any(value is not None and (type(value) is not int or value < 0) for value in counts):
                raise ValueError
            usage = TokenUsage(input_tokens=counts[0], output_tokens=counts[1])
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError("timeout") from None
        except httpx.TransportError:
            raise ProviderError("connection_error", transient=True) from None
        except (ValueError, TypeError, ValidationError):
            raise ProviderError("invalid_provider_response") from None
        try:
            content = ModelAnswer.model_validate_json(message.get("content", ""))
        except (ValidationError, ValueError, TypeError):
            raise ProviderError("invalid_structured_response", usage=usage) from None
        return ProviderAnswer(content=content, usage=usage)

    async def _request(self, client, body):
        async with client.stream("POST", self.endpoint + "/api/chat", json=body,
                                 timeout=self.settings.LLM_TIMEOUT_SECONDS, follow_redirects=False) as response:
            if 300 <= response.status_code < 400:
                raise ProviderError("provider_redirect_denied")
            if response.status_code == 404:
                raise ProviderError("model_unavailable")
            if response.status_code != 200:
                raise ProviderError("provider_error", transient=response.status_code >= 500)
            output = bytearray()
            async for chunk in response.aiter_bytes():
                output.extend(chunk)
                if len(output) > MAX_RESPONSE_BYTES:
                    raise ProviderError("provider_output_size")
            return bytes(output)
