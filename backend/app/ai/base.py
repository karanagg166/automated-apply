"""Provider-independent interface: one invocation is at most one billed request."""
from typing import Protocol
from backend.app.ai.schemas import ProviderAnswer, TokenUsage


class ProviderError(Exception):
    def __init__(self, code: str, *, transient=False, retry_after: float | None = None, usage: TokenUsage | None = None):
        super().__init__(code)  # Never propagate provider messages containing prompts or secrets.
        self.code, self.transient, self.retry_after, self.usage = code, transient, retry_after, usage
        self.attempted = False


class ApplicationLLMProvider(Protocol):
    async def generate_structured_answer(self, question: str, grounded_context: dict, instructions: dict) -> ProviderAnswer: ...
