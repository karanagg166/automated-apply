"""Optional HTTP models use the existing grounded contract and durable request budget.

Ollama is restricted to the local loopback service. Cohere is evaluation-only, requires
explicit data sharing and trial entitlement attestations, and is never selected implicitly.
Neither provider receives raw resume PDFs, browser HTML, cookies or credentials.
"""

import json

import httpx
from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import provider_prompt
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage


class OptionalProvider:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client

    async def _local_metadata(self, client):
        """No private prompt leaves the process until the daemon proves local mode.

        Older daemons without /api/status fail closed. A loopback URL alone does
        not establish locality: Ollama can proxy cloud models through that URL.
        """
        try:
            for method, endpoint, body in [
                ("GET", "status", None),
                ("POST", "show", {"model": self.settings.OLLAMA_MODEL}),
            ]:
                async with client.stream(
                    method,
                    "http://127.0.0.1:11434/api/" + endpoint,
                    **({"json": body} if body is not None else {}),
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError("local_model_unverified")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 262144:
                            raise ProviderError("local_model_unverified")
                    data = json.loads(raw)
                if endpoint == "status":
                    if data.get("cloud", {}).get("disabled") is not True:
                        raise ProviderError("local_model_unverified")
                elif (
                    data.get("remote_host")
                    or data.get("remote_model")
                    or not isinstance(data.get("model_info"), dict)
                    or not data["model_info"]
                ):
                    raise ProviderError("local_model_unverified")
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderError("timeout") from None
        except httpx.TransportError:
            raise ProviderError("connection_error") from None
        except (ValueError, TypeError, AttributeError):
            raise ProviderError("local_model_unverified") from None

    async def generate_structured_answer(
        self, question, grounded_context, instructions
    ):
        if self.client is not None:
            return await self._call(
                self.client, question, grounded_context, instructions
            )
        async with httpx.AsyncClient(
            timeout=self.settings.LLM_TIMEOUT_SECONDS,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            return await self._call(client, question, grounded_context, instructions)

    async def _call(self, client, question, context, instructions):
        settings = self.settings
        local = settings.LLM_PROVIDER == "ollama"
        system, payload, contract = provider_prompt(
            question, context, instructions, settings.LLM_PROVIDER
        )
        if len(payload) + len(system) > settings.LLM_MAX_INPUT_CHARS:
            raise ProviderError("input_limit_exceeded")
        if local:
            if not settings.OLLAMA_MODEL or not settings.OLLAMA_ENABLED:
                raise ProviderError("llm_not_configured")
            await self._local_metadata(client)
            url = "http://127.0.0.1:11434/api/generate"
            headers = {}
            body = {
                "model": settings.OLLAMA_MODEL,
                "stream": False,
                "system": system,
                "prompt": payload,
                "format": contract,
                "options": {
                    "temperature": 0,
                    "num_predict": settings.LLM_MAX_OUTPUT_TOKENS,
                },
            }
        else:
            # Check again at the transport boundary, even when instantiated without the factory.
            if not (
                settings.ENVIRONMENT == "testing"
                and settings.COHERE_EVALUATION_ENABLED
                and settings.COHERE_TRIAL_KEY_CONFIRMED
                and settings.COHERE_DATA_SHARING_APPROVED
                and settings.COHERE_API_KEY
                and settings.COHERE_MODEL
            ):
                raise ProviderError("provider_permission_required")
            url = "https://api.cohere.com/v2/chat"
            headers = {
                "Authorization": "Bearer " + settings.COHERE_API_KEY.get_secret_value()
            }
            body = {
                "model": settings.COHERE_MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": system + "\nReturn JSON only.",
                    },
                    {"role": "user", "content": payload},
                ],
                "response_format": {
                    "type": "json_object",
                    "schema": ModelAnswer.model_json_schema(),
                },
                "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
                "temperature": 0.2,
            }
        try:
            # Bound the body before parsing; never retain provider error text containing private data.
            async with client.stream(
                "POST", url, json=body, headers=headers
            ) as response:
                if response.status_code == 429:
                    raise ProviderError("rate_limited", retry_after=60)
                if response.status_code in {401, 403}:
                    raise ProviderError("provider_authentication")
                if response.status_code != 200:
                    raise ProviderError("provider_unavailable")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 131072:
                        raise ProviderError("invalid_structured_response")
                data = json.loads(raw)
            if local:
                if data.get("remote_host") or data.get("remote_model"):
                    raise ProviderError("local_model_unverified")
                if data.get("done") is not True:
                    raise ProviderError("invalid_structured_response")
                content = ModelAnswer.model_validate_json(data["response"])
                usage = TokenUsage(
                    input_tokens=data.get("prompt_eval_count"),
                    output_tokens=data.get("eval_count"),
                )
            else:
                if data.get("finish_reason") != "COMPLETE":
                    raise ProviderError("invalid_structured_response")
                content = ModelAnswer.model_validate_json(
                    data["message"]["content"][0]["text"]
                )
                usage = TokenUsage(**data.get("usage", {}).get("billed_units", {}))
            return ProviderAnswer(content=content, usage=usage)
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderError("timeout") from None
        except httpx.TransportError:
            raise ProviderError("connection_error") from None
        except (ValidationError, ValueError, TypeError, KeyError, IndexError):
            raise ProviderError("invalid_structured_response") from None
