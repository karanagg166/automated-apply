"""Configuration is checked only for generation, never for deterministic features."""

from backend.app.ai.base import ApplicationLLMProvider, ProviderError
from backend.app.core.config import Settings


def create_provider(settings: Settings) -> ApplicationLLMProvider:
    if settings.LLM_PROVIDER == "cohere":
        if not settings.COHERE_ENABLED:
            from backend.app.ai.providers.optional import OptionalProvider

            if not (
                settings.ENVIRONMENT == "testing"
                and settings.COHERE_EVALUATION_ENABLED
                and settings.COHERE_TRIAL_KEY_CONFIRMED
                and settings.COHERE_DATA_SHARING_APPROVED
                and settings.COHERE_API_KEY
                and settings.COHERE_MODEL
            ):
                raise ProviderError("provider_permission_required")
            return OptionalProvider(settings)
        from backend.app.ai.providers.cohere import CohereProvider

        return CohereProvider(settings)
    if settings.LLM_PROVIDER == "agy":
        from backend.app.ai.providers.agy import AgyProvider

        return AgyProvider(settings)
    if settings.LLM_PROVIDER == "ollama":
        if settings.OLLAMA_ENABLED:
            from backend.app.ai.providers.optional import OptionalProvider

            if not settings.OLLAMA_MODEL:
                raise ProviderError("llm_not_configured")
            return OptionalProvider(settings)
        if not settings.OLLAMA_GENERATION_AUTHORIZED:
            raise ProviderError("provider_execution_not_authorized")
        from backend.app.ai.providers.ollama import OllamaProvider

        return OllamaProvider(settings)
    if settings.LLM_PROVIDER != "gemini":
        raise ProviderError("unsupported_provider")
    if (
        not settings.GEMINI_API_KEY
        or not settings.GEMINI_API_KEY.get_secret_value().strip()
        or not settings.LLM_MODEL
    ):
        raise ProviderError("llm_not_configured")
    if not settings.GEMINI_ENABLED or settings.GEMINI_APPROVED_MONTHLY_REQUESTS <= 0:
        raise ProviderError("provider_permission_required")
    if not settings.GEMINI_CANDIDATE_DATA_AUTHORIZED:
        raise ProviderError("candidate_cloud_authorization_required")
    from backend.app.ai.providers.gemini import GeminiProvider

    return GeminiProvider(settings)


def configured_model(settings: Settings) -> str | None:
    if settings.LLM_PROVIDER == "cohere":
        return settings.COHERE_MODEL
    if settings.LLM_PROVIDER == "agy":
        return settings.AGY_MODEL
    if settings.LLM_PROVIDER == "ollama":
        return settings.OLLAMA_MODEL
    return settings.LLM_MODEL
