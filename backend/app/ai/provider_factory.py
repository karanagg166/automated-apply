"""Configuration is checked only for generation, never for deterministic features."""
from backend.app.ai.base import ApplicationLLMProvider, ProviderError
from backend.app.core.config import Settings


def create_provider(settings: Settings) -> ApplicationLLMProvider:
    if settings.LLM_PROVIDER == "agy":
        from backend.app.ai.providers.agy import AgyProvider
        return AgyProvider(settings)
    if settings.LLM_PROVIDER == "ollama":
        from backend.app.ai.providers.ollama import OllamaProvider
        return OllamaProvider(settings)
    if settings.LLM_PROVIDER != "gemini":
        raise ProviderError("unsupported_provider")
    if not settings.GEMINI_API_KEY or not settings.GEMINI_API_KEY.get_secret_value().strip() or not settings.LLM_MODEL:
        raise ProviderError("llm_not_configured")
    from backend.app.ai.providers.gemini import GeminiProvider
    return GeminiProvider(settings)
