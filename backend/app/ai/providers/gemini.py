"""Current google-genai async structured output API. No tools or URL retrieval."""
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage


def retry_after_seconds(response):
    raw = response.headers.get("retry-after") if response is not None else None
    if not raw:
        return None
    try:
        value = float(raw)
        return max(0, value) if math.isfinite(value) else None
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class GeminiProvider:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client

    async def generate_structured_answer(self, question, grounded_context, instructions):
        if not self.settings.GEMINI_ENABLED or self.settings.GEMINI_APPROVED_MONTHLY_REQUESTS<=0:
            raise ProviderError("provider_permission_required")
        if self.client is not None:
            return await self._call(self.client, question, grounded_context, instructions)
        # Disable hidden SDK retries: every network attempt is separately reserved by our quota layer.
        async with genai.Client(
            api_key=self.settings.GEMINI_API_KEY.get_secret_value(),
            http_options=types.HttpOptions(timeout=int(self.settings.LLM_TIMEOUT_SECONDS * 1000),
                                           retry_options=types.HttpRetryOptions(attempts=1)),
        ).aio as client:
            return await self._call(client, question, grounded_context, instructions)

    async def _call(self, client, question, grounded_context, instructions):
        try:
            response = await client.models.generate_content(
                model=self.settings.LLM_MODEL,
                contents=build_payload(question, grounded_context, instructions),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION, response_mime_type="application/json",
                    response_schema=ModelAnswer, temperature=0.2,
                    max_output_tokens=self.settings.LLM_MAX_OUTPUT_TOKENS,
                ),
            )
        except errors.APIError as exc:
            code = exc.code
            if code == 429:
                raise ProviderError("rate_limited", retry_after=retry_after_seconds(exc.response)) from None
            mapping = {400: "invalid_provider_request", 401: "provider_authentication", 403: "provider_authentication", 404: "model_unavailable"}
            raise ProviderError(mapping.get(code, "provider_error"), transient=code in {500, 502, 503, 504},
                                retry_after=retry_after_seconds(exc.response)) from None
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderError("timeout") from None
        except httpx.TransportError:
            raise ProviderError("connection_error", transient=True) from None
        metadata = response.usage_metadata
        usage = TokenUsage(input_tokens=metadata.prompt_token_count if metadata else None,
                           output_tokens=metadata.candidates_token_count if metadata else None)
        try:
            content = ModelAnswer.model_validate_json(response.text or "")
        except (ValidationError, ValueError, TypeError):
            raise ProviderError("invalid_structured_response", usage=usage) from None
        return ProviderAnswer(content=content, usage=usage)
