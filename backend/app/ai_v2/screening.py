"""4-tier screening answer pipeline (deterministic first, LLM last).

Tier 0  verified profile facts (browser_v2.answers)       0 tokens, ~0 ms
Tier 1  local semantic cache (exact, then cosine >= 0.88   0 tokens, ~5 ms
        + qualifier-mismatch guard)
Tier 2  free external LLM router (PII-scrubbed, strict JSON, options-constrained)
Tier 3  None -> caller marks the job WAITING_FOR_USER (HITL)

Sensitive questions (passwords, OTPs, IDs, consent, demographics) skip
Tiers 1-2. Questions asking for private/unverified personal data skip Tier 2.

Degradation contract (Workstream 3): resolve() never raises. A failing tier
(cache backend error, zero LLM keys, every provider 429/5xx, malformed reply,
usage-store outage) is logged and the chain falls through to the next tier and
finally to Tier 3 (None -> HITL), so the 24/7 worker can never crash here.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter
from backend.app.ai_v2.semantic_cache import SemanticCache
from backend.app.browser_v2.answers import (
    BLOCKED,
    SENSITIVE,
    CandidateFacts,
    choose_option,
    choose_yes_no,
    resolve_answer,
)

logger = logging.getLogger(__name__)

KIND = "screening_qa"
ACCEPT_CONFIDENCE = 0.80
CACHE_CONFIDENCE = 0.85
# Facts an LLM can never know or verify: these always go to the human.
PRIVATE_REQUEST = re.compile(
    r"\b(?:date of birth|dob|birth ?date|age\b|father|mother|spouse|marital|home address|street|"
    r"permanent address|pin ?code|zip|postal code|phone|mobile|contact number|whatsapp|e-?mail|"
    r"linkedin|github|portfolio|personal (?:website|link)|url|link to|manager(?:'s)? name|"
    r"reporting manager|reference|referee|salary slip|pay ?slip|payslip|offer letter|relieving letter|"
    r"proof|uan|pf number|passport|visa number|license number|licence number|id number|"
    r"employee id|roll number|registration number|cgpa|gpa|percentage|marks|graduation year|"
    r"passing year|college name|university name|current company|current employer|last working day|"
    r"criminal|convicted|medical|health|blood group|caste|category|nationality|citizenship)\b",
    re.IGNORECASE)

SYSTEM_PROMPT = (
    "You fill job-application screening questions for one candidate. Use ONLY the facts in the "
    "candidate profile JSON. Never invent dates, employers, compensation, certifications, links, "
    "IDs or work authorization. If the profile does not clearly answer the question, set "
    "needs_human=true and answer=null. When options are given, answer must be exactly one option "
    "string. Keep free-text answers under 300 characters, first person, factual. Set cacheable=true "
    "only when the answer does not depend on this specific company or job. Reply with one JSON "
    'object: {"answer": string|null, "confidence": number 0-1, "needs_human": boolean, '
    '"cacheable": boolean, "reason": string}.')


class LLMScreeningAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool = False
    cacheable: bool = False
    reason: str = Field(default="", max_length=500)

    @field_validator("answer", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)):
            return str(int(value)) if float(value).is_integer() else str(value)
        if isinstance(value, str) and not value.strip():
            return None
        return value


@dataclass(frozen=True)
class ResolvedAnswer:
    answer: str | None
    tier: int
    source: str  # profile | semantic_cache | llm | human
    latency_ms: float
    reason: str = ""
    cache_match: str | None = None
    similarity: float | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    confidence: float | None = None
    cached_new: bool = False
    llm_chain: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, (), "")}


def fit_to_options(answer: str, options: tuple[str, ...]) -> str | None:
    """Map a cached/LLM answer onto the exact option string (None if it does not fit)."""
    if not options:
        return answer
    exact = choose_option(options, answer)
    if exact is not None:
        return exact
    lowered = answer.strip().lower()
    if lowered in {"yes", "y", "true"}:
        return choose_yes_no(options, True)
    if lowered in {"no", "n", "false"}:
        return choose_yes_no(options, False)
    return None


class ScreeningAnswerer:
    def __init__(self, cache: SemanticCache | None, router: LLMRouter | None, *,
                 accept_confidence: float = ACCEPT_CONFIDENCE, cache_confidence: float = CACHE_CONFIDENCE,
                 save_llm_answers: bool = True) -> None:
        self.cache = cache
        self.router = router
        self.accept_confidence = accept_confidence
        self.cache_confidence = cache_confidence
        self.save_llm_answers = save_llm_answers
        self.safe_profile: dict[str, Any] = {}

    def bind_profile(self, safe_profile: dict[str, Any]) -> None:
        self.safe_profile = dict(safe_profile)

    async def resolve(self, question: str, options: tuple[str, ...], facts: CandidateFacts,
                      context: dict[str, Any] | None = None) -> ResolvedAnswer:
        started = time.perf_counter()

        def elapsed() -> float:
            return round((time.perf_counter() - started) * 1000, 2)

        try:
            deterministic = resolve_answer(question, options, facts)
        except Exception:  # a matcher bug must degrade to the next tier, never crash
            logger.exception("screening_tier0_failed")
            deterministic = None
        if deterministic is not None:
            return ResolvedAnswer(deterministic, 0, "profile", elapsed(), "profile_fact")
        if not question.strip() or BLOCKED.search(question) or SENSITIVE.search(question):
            return ResolvedAnswer(None, 3, "human", elapsed(), "sensitive_or_blocked_question")
        if self.cache is not None:
            try:
                hit = await self.cache.lookup(KIND, question)
            except Exception:  # cache outage: fall through (LLM or HITL)
                logger.exception("screening_cache_lookup_failed")
                hit = None
            if hit is not None:
                fitted = fit_to_options(hit.entry.answer_text, options)
                if fitted is not None:
                    return ResolvedAnswer(fitted, 1, "semantic_cache", elapsed(), f"cache_{hit.entry.source}",
                                          cache_match=hit.match, similarity=round(hit.similarity, 4))
        if PRIVATE_REQUEST.search(question):
            return ResolvedAnswer(None, 3, "human", elapsed(), "private_or_unverifiable_data")
        try:
            configured = self.router is not None and bool(self.router.any_configured)
        except Exception:
            logger.exception("screening_router_status_failed")
            configured = False
        if not configured:
            return ResolvedAnswer(None, 3, "human", elapsed(), "llm_unconfigured")
        try:
            return await self._llm(question, options, context or {}, started)
        except Exception as exc:  # noqa: BLE001 - any LLM/usage-store failure -> HITL, never a crash
            logger.warning("screening_llm_failed: %s", type(exc).__name__)
            return ResolvedAnswer(None, 3, "human", _ms(started), f"llm_error:{type(exc).__name__}")

    async def _llm(self, question: str, options: tuple[str, ...], context: dict[str, Any],
                   started: float) -> ResolvedAnswer:
        assert self.router is not None
        job = {k: context.get(k) for k in ("title", "company") if context.get(k)}
        user_prompt = json.dumps({"candidate_profile": self.safe_profile, "job": job, "question": question,
                                  "options": list(options)}, ensure_ascii=False)
        try:
            result = await self.router.generate_json("screening_qa", SYSTEM_PROMPT, user_prompt,
                                                     LLMScreeningAnswer, max_output_tokens=300)
        except AllLLMProvidersExhaustedError as exc:
            return ResolvedAnswer(None, 3, "human", _ms(started), "llm_exhausted",
                                  llm_chain=tuple(f"{a['provider']}:{a['outcome']}" for a in exc.attempts))
        reply = result.value
        human = ResolvedAnswer(None, 3, "human", 0.0, "", provider=result.provider, model=result.model,
                               input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                               confidence=reply.confidence)
        if reply.needs_human or reply.answer is None:
            return replace(human, latency_ms=_ms(started), reason="llm_needs_human")
        if reply.confidence < self.accept_confidence:
            return replace(human, latency_ms=_ms(started), reason="llm_low_confidence")
        fitted = fit_to_options(reply.answer, options)
        if fitted is None:
            return replace(human, latency_ms=_ms(started), reason="llm_answer_not_an_option")
        cached = False
        if self.save_llm_answers and self.cache is not None and reply.cacheable \
                and reply.confidence >= self.cache_confidence:
            try:
                await self.cache.put(KIND, question, fitted, "llm")
                cached = True
            except Exception:  # the accepted answer is still usable without caching
                logger.exception("screening_cache_put_failed")
        return replace(human, answer=fitted, tier=2, source="llm", latency_ms=_ms(started),
                       reason="llm_accepted", cached_new=cached)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
