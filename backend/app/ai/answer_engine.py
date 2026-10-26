"""Version 1 opt-in answer orchestration; integration requires service adoption.

The legacy ProviderAnswer cannot represent an abstention or truthful fallback
provenance. Keep this internal contract separate instead of forging a model claim.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from backend.app.ai.base import ProviderError
from backend.app.ai.evidence import match_answer, prepare_evidence
from backend.app.ai.schemas import ModelAnswer, TokenUsage


@dataclass(frozen=True)
class SafeAnswerV1:
    source: Literal["deterministic_extractive", "ollama_generated_verified", "needs_input", "validation_failed"]
    content: ModelAnswer | None = None
    missing_information: tuple[str, ...] = ()
    error_code: str | None = None
    model_attempted: bool = False
    usage: TokenUsage | None = None
    contract_version: str = "local_answer.v1"

    @property
    def status(self):
        return "draft_ready" if self.content else self.source

    @property
    def used_llm(self):
        return self.source == "ollama_generated_verified"


class LocalAnswerEngine:
    def __init__(self, provider_factory=None):
        # Lazy construction: no daemon access, authorization or model loading for extraction.
        self.provider_factory = provider_factory
        self._inflight = {}

    async def answer(self, question, context, instructions, *, rewrite=False,
                     low_memory=False, route="narrative"):
        if route in {"profile_link", "resume_status"}:
            return SafeAnswerV1("needs_input", missing_information=("Resolve using the existing profile/resume resolver.",))
        prepared = prepare_evidence(question, context, instructions)
        if prepared.missing:
            return SafeAnswerV1("needs_input", missing_information=prepared.missing)
        if prepared.error:
            return SafeAnswerV1("validation_failed", error_code=prepared.error)
        deterministic, error = match_answer(" ".join(c.text for c in prepared.clauses), prepared,
                                            context["evidence"], instructions)
        if error:
            return SafeAnswerV1("validation_failed", error_code=error)
        fallback = SafeAnswerV1("deterministic_extractive", content=deterministic)
        if (not rewrite or low_memory or route in {"factual_extraction", "approved_summary"}
                or len(prepared.clauses) < 2 or self.provider_factory is None):
            return fallback
        # Coalesce overlapping identical requests only; no lasting candidate cache.
        key = hashlib.sha256(json.dumps([question, context, instructions], sort_keys=True).encode()).digest()
        if key not in self._inflight:
            if len(self._inflight) >= 8:
                return fallback
            self._inflight[key] = [asyncio.create_task(self._rewrite(
                prepared, context, instructions, deterministic)), 0]
        entry = self._inflight[key]
        entry[1] += 1
        try:
            return await asyncio.shield(entry[0])
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._inflight.pop(key, None)
                if not entry[0].done():
                    entry[0].cancel()
                    try:
                        await entry[0]
                    except asyncio.CancelledError:
                        pass

    async def _rewrite(self, prepared, context, instructions, deterministic):
        attempted = False
        try:
            provider = self.provider_factory()
            attempted = True
            response = await provider.rewrite_prepared(prepared, context, instructions)
            # Recheck even injected providers. No trusted bypass around sentence matching.
            content, error = match_answer(response.content.answer, prepared, context["evidence"], instructions)
            if error:
                raise ProviderError(error, usage=response.usage)
            return SafeAnswerV1("ollama_generated_verified", content=content,
                                model_attempted=True, usage=response.usage)
        except ProviderError as exc:
            return SafeAnswerV1("deterministic_extractive", content=deterministic,
                                error_code=exc.code, model_attempted=attempted, usage=exc.usage)
