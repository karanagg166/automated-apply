"""Configuration is checked only for generation, never for deterministic features."""
from backend.app.ai.base import ApplicationLLMProvider, ProviderError
from backend.app.core.config import Settings


def create_provider(settings: Settings) -> ApplicationLLMProvider:
    if settings.LLM_PROVIDER in {"ollama", "cohere"}:
        from backend.app.ai.providers.optional import OptionalProvider
        if settings.LLM_PROVIDER == "ollama" and not (settings.OLLAMA_ENABLED and settings.OLLAMA_MODEL):
            raise ProviderError("llm_not_configured")
        if settings.LLM_PROVIDER == "cohere" and not (
            settings.ENVIRONMENT == "testing" and settings.COHERE_EVALUATION_ENABLED
            and settings.COHERE_TRIAL_KEY_CONFIRMED and settings.COHERE_DATA_SHARING_APPROVED
            and settings.COHERE_API_KEY and settings.COHERE_MODEL
        ):
            raise ProviderError("provider_permission_required")
        return OptionalProvider(settings)
    if settings.LLM_PROVIDER != "gemini":
        raise ProviderError("unsupported_provider")
    if not settings.GEMINI_API_KEY or not settings.GEMINI_API_KEY.get_secret_value().strip() or not settings.LLM_MODEL:
        raise ProviderError("llm_not_configured")
    from backend.app.ai.providers.gemini import GeminiProvider
    return GeminiProvider(settings)
