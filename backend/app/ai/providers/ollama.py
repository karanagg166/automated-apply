"""Isolated local Ollama provider for resource-constrained environments (e.g. 8 GB Mac).

Design constraints:
- Loopback only: 127.0.0.1:11434, no external network egress.
- Tool-free: No tools or delegation advertised or supported.
- Memory-bounded: Suitable for small quantized models (e.g. qwen2.5:1.5b ~1.4 GB, context 2048).
- Single-model: OLLAMA_MAX_LOADED_MODELS=1.
- Strict structured output: enforced via Ollama's schema/format parameter and Pydantic validation.
- Inactive by default: Requires explicit owner installation, model pull, and configuration activation.
"""
import json
from typing import Any

import httpx
from pydantic import ValidationError

from backend.app.ai.base import ApplicationLLMProvider, ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b-instruct"


class OllamaProvider(ApplicationLLMProvider):
    def __init__(self, settings: Any, client: httpx.AsyncClient | None = None, endpoint: str = DEFAULT_OLLAMA_ENDPOINT):
        self.settings = settings
        self.client = client
        self.endpoint = endpoint.rstrip("/")
        # Strictly enforce loopback endpoint
        if not (self.endpoint.startswith("http://127.0.0.1:") or self.endpoint.startswith("http://localhost:")):
            raise ProviderError("ollama_endpoint_must_be_loopback")
        self.model = getattr(settings, "OLLAMA_MODEL", None) or DEFAULT_OLLAMA_MODEL

    async def generate_structured_answer(self, question: str, grounded_context: dict, instructions: dict) -> ProviderAnswer:
        payload = build_payload(question, grounded_context, instructions)
        if len(payload) > getattr(self.settings, "LLM_MAX_INPUT_CHARS", 16000):
            raise ProviderError("input_size_exceeded")

        schema = ModelAnswer.model_json_schema()
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": payload},
            ],
            "format": schema,
            "options": {
                "temperature": 0.2,
                "num_ctx": 2048,
                "num_predict": getattr(self.settings, "LLM_MAX_OUTPUT_TOKENS", 1000),
            },
            "stream": False,
        }

        timeout = getattr(self.settings, "LLM_TIMEOUT_SECONDS", 30.0)

        try:
            if self.client is not None:
                response = await self.client.post(f"{self.endpoint}/api/chat", json=request_body, timeout=timeout)
            else:
                async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                    response = await client.post(f"{self.endpoint}/api/chat", json=request_body)

            if response.status_code == 404:
                raise ProviderError("model_unavailable")
            if response.status_code != 200:
                raise ProviderError("provider_error", transient=response.status_code >= 500)

            data = response.json()
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.TransportError:
            raise ProviderError("connection_error", transient=True) from None
        except (json.JSONDecodeError, ValueError):
            raise ProviderError("invalid_provider_response") from None

        message_content = data.get("message", {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count")
        eval_tokens = data.get("eval_count")
        usage = TokenUsage(input_tokens=prompt_tokens, output_tokens=eval_tokens)

        try:
            content = ModelAnswer.model_validate_json(message_content)
        except (ValidationError, ValueError, TypeError):
            raise ProviderError("invalid_structured_response", usage=usage) from None

        return ProviderAnswer(content=content, usage=usage)
