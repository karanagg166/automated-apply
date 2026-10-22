"""One explicit primary provider and optional local-only fallback under a shared deadline."""

import asyncio
from dataclasses import dataclass

from backend.app.ai.base import ProviderError
from backend.app.ai.optional_usage import OptionalUsageManager
from backend.app.ai.provider_factory import create_provider
from backend.app.ai.schemas import ProviderAnswer
from backend.app.ai.usage import LLMUsageManager


@dataclass
class Generation:
    response: ProviderAnswer
    provider: str
    model: str | None
    fallback_from: str | None = None


def model_name(settings):
    return (
        settings.OLLAMA_MODEL
        if settings.LLM_PROVIDER == "ollama"
        else settings.COHERE_MODEL
        if settings.LLM_PROVIDER == "cohere"
        else settings.LLM_MODEL
    )


async def generate(settings, usage, provider_override, question, context, instructions):
    allowed = (
        settings.LLM_LOCAL_FALLBACK_ENABLED
        and settings.OLLAMA_ENABLED
        and settings.OLLAMA_MODEL
        and settings.LLM_PROVIDER != "ollama"
    )
    primary_settings = (
        settings.model_copy(
            update={"LLM_TIMEOUT_SECONDS": max(1, settings.LLM_TIMEOUT_SECONDS * 0.55)}
        )
        if allowed
        else settings
    )
    primary_usage = usage
    if allowed and isinstance(usage, (LLMUsageManager, OptionalUsageManager)):
        primary_usage = type(usage)(
            usage.factory,
            usage.settings.model_copy(
                update={"LLM_TIMEOUT_SECONDS": primary_settings.LLM_TIMEOUT_SECONDS}
            ),
        )
    attempted = False
    active_provider, active_model = settings.LLM_PROVIDER, model_name(settings)
    try:
        async with asyncio.timeout(settings.LLM_TIMEOUT_SECONDS):
            try:
                provider = provider_override or create_provider(primary_settings)
                response = await primary_usage.generate(
                    provider, question, context, instructions
                )
                return Generation(
                    ProviderAnswer.model_validate(response),
                    settings.LLM_PROVIDER,
                    model_name(settings),
                )
            except ProviderError as failure:
                attempted = failure.attempted
                if not allowed:
                    raise
                # No fallback ever selects or enables another remote provider.
                fallback_from = failure.code
            local = settings.model_copy(update={"LLM_PROVIDER": "ollama"})
            active_provider, active_model = "ollama", local.OLLAMA_MODEL
            provider = create_provider(local)
            local_usage = OptionalUsageManager(usage.factory, local)
            response = await local_usage.generate(
                provider, question, context, instructions
            )
            return Generation(
                ProviderAnswer.model_validate(response),
                "ollama",
                local.OLLAMA_MODEL,
                fallback_from,
            )
    except ProviderError as error:
        error.provider, error.model = active_provider, active_model
        error.attempted = error.attempted or attempted
        raise
    except TimeoutError:
        error = ProviderError("timeout")
        error.attempted = attempted
        error.provider, error.model = active_provider, active_model
        raise error from None
