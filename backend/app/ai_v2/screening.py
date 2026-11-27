"""4-tier screening answer pipeline (deterministic first, LLM last).

Tier 0  verified profile facts (browser_v2.answers)       0 tokens, ~0 ms
Tier 1  local semantic cache (exact, then cosine >= 0.88   0 tokens, ~5 ms
        + qualifier-mismatch guard)
Tier 2  free external LLM router (PII-scrubbed, strict JSON, options-constrained),
        then an LLM judge from another provider audits the answer (ai_v2.judge)
Tier 3  None -> caller marks the job WAITING_FOR_USER (HITL)

Sensitive questions (passwords, OTPs, IDs, consent, demographics) skip
Tiers 1-2. Owner-declared disclosures (EEO, consent, NDA signature; see
browser_v2.answers.disclosures) are answered in Tier 0 before that gate and are
never written to the semantic cache. Questions asking for private/unverified
personal data skip Tier 2.

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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.ai_v2.observability import trace_context
from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter
from backend.app.ai_v2.semantic_cache import SemanticCache
from backend.app.browser_v2.answers import (
    BLOCKED,
    SENSITIVE,
    CandidateFacts,
    choose_option,
    choose_yes_no,
    disclosure_answer,
    resolve_answer,
)

if TYPE_CHECKING:
    from backend.app.ai_v2.judge import AnswerJudge

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
    judge: str | None = None  # approved | rejected (None = not judged)
    trace_id: str | None = None

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
                 save_llm_answers: bool = True, judge: AnswerJudge | None = None) -> None:
        self.cache = cache
        self.judge = judge
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
            handled, disclosed = disclosure_answer(question, options, facts)
        except Exception:  # a matcher bug must degrade to the human, never crash
            logger.exception("screening_disclosure_failed")
            handled, disclosed = True, None
        if handled:  # owner-declared EEO / consent / NDA fact: Tier 0 or the human, never cache / LLM
            return ResolvedAnswer(disclosed, 0 if disclosed is not None else 3,
                                  "profile" if disclosed is not None else "human", elapsed(),
                                  "owner_disclosure" if disclosed is not None else "disclosure_no_safe_option")
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
            with trace_context(tags=["feature:screening"], metadata={
                    "portal": context.get("platform") or context.get("portal"), "company": job.get("company"),
                    "role": job.get("title"), "has_options": bool(options)}):
                result = await self.router.generate_json("screening_qa", SYSTEM_PROMPT, user_prompt,
                                                         LLMScreeningAnswer, max_output_tokens=300)
        except AllLLMProvidersExhaustedError as exc:
            return ResolvedAnswer(None, 3, "human", _ms(started), "llm_exhausted",
                                  llm_chain=tuple(f"{a['provider']}:{a['outcome']}" for a in exc.attempts))
        reply = result.value
        human = ResolvedAnswer(None, 3, "human", 0.0, "", provider=result.provider, model=result.model,
                               input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                               confidence=reply.confidence, trace_id=result.trace_id)

        def punt(reason: str, **extra: Any) -> ResolvedAnswer:
            self._score(result.trace_id, False, reply.confidence, reason)
            return replace(human, latency_ms=_ms(started), reason=reason, **extra)

        if reply.needs_human or reply.answer is None:
            return punt("llm_needs_human")
        if reply.confidence < self.accept_confidence:
            return punt("llm_low_confidence")
        fitted = fit_to_options(reply.answer, options)
        if fitted is None:
            return punt("llm_answer_not_an_option")
        verdict = None
        if self.judge is not None:
            verdict = await self.judge.review(
                question=question, options=options, answer=fitted, safe_profile=self.safe_profile, job=job,
                generator=result.provider, trace_id=result.trace_id)
        rejected = verdict is not None and not verdict.approved
        label = verdict.label if verdict is not None else None
        if rejected and self.judge is not None and self.judge.enforce:
            return punt("llm_judge_rejected", judge=label)
        self._score(result.trace_id, True, reply.confidence, "llm_accepted")
        cached = False
        if self.save_llm_answers and self.cache is not None and reply.cacheable and not rejected \
                and reply.confidence >= self.cache_confidence:
            try:
                await self.cache.put(KIND, question, fitted, "llm")
                cached = True
            except Exception:  # the accepted answer is still usable without caching
                logger.exception("screening_cache_put_failed")
        return replace(human, answer=fitted, tier=2, source="llm", latency_ms=_ms(started),
                       reason="llm_accepted", cached_new=cached, judge=label)

    def _score(self, trace_id: str | None, accepted: bool, confidence: float, reason: str) -> None:
        """Outcome scores on the generator's trace (no-op when tracing is off)."""
        tracer = getattr(self.router, "tracer", None)
        if tracer is None or not trace_id:
            return
        tracer.score(trace_id, "answer_accepted", accepted, comment=reason)
        tracer.score(trace_id, "llm_confidence", confidence, comment=reason)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
