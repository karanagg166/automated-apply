"""Gray-zone JD tie-breaker: only for jobs that passed every hard filter but whose
title only partially matches the target roles. Decisions are cached exactly
(kind='jd_score'), so the same posting is never scored twice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter
from backend.app.ai_v2.semantic_cache import SemanticCache, normalize_question

KIND = "jd_score"
DEFAULT_MIN_SCORE = 0.70
MAX_JD_CHARS = 6_000

SYSTEM_PROMPT = (
    "You decide whether a job posting fits a candidate's target roles and skills. Judge only role "
    "fit (responsibilities, seniority, stack), not company prestige. Reply with one JSON object: "
    '{"match": boolean, "score": number 0-1, "reason": string under 200 characters}.')


class LLMJDScore(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


@dataclass(frozen=True)
class JDDecision:
    accepted: bool
    score: float
    reason: str
    source: str  # llm | cache
    provider: str | None = None


def cache_key(title: str, company: str | None, description: str, target_roles: tuple[str, ...]) -> str:
    digest = hashlib.sha256(description.encode()).hexdigest()[:16]
    return f"{title} | {company or ''} | targets {', '.join(sorted(target_roles))} | jd {digest}"


class JDScorer:
    def __init__(self, router: LLMRouter | None, cache: SemanticCache | None, *,
                 min_score: float = DEFAULT_MIN_SCORE) -> None:
        self.router = router
        self.cache = cache
        self.min_score = min_score
        self.safe_profile: dict[str, Any] = {}

    def bind_profile(self, safe_profile: dict[str, Any], min_score: float | None = None) -> None:
        self.safe_profile = dict(safe_profile)
        if min_score is not None and 0.0 < min_score <= 1.0:
            self.min_score = min_score

    @property
    def available(self) -> bool:
        return self.router is not None and bool(self.router.configured_chain("jd_scoring"))

    async def score(self, *, title: str, company: str | None, description: str,
                    target_roles: tuple[str, ...]) -> JDDecision | None:
        """None = no decision possible (no providers / all exhausted): caller keeps the deterministic verdict."""
        key = cache_key(title, company, description, target_roles)
        if self.cache is not None:
            hit = await self.cache.lookup(KIND, key, semantic=False)
            if hit is not None:
                try:
                    data = LLMJDScore.model_validate(json.loads(hit.entry.answer_text))
                except (ValueError, TypeError):
                    data = None
                if data is not None:
                    return JDDecision(data.match and data.score >= self.min_score, data.score, data.reason, "cache")
        if not self.available:
            return None
        assert self.router is not None
        user_prompt = json.dumps({"candidate": {k: self.safe_profile.get(k) for k in (
            "target_roles", "tech_stack", "skills", "skill_years", "total_experience_years", "remote_policy")},
            "job": {"title": title, "description": description[:MAX_JD_CHARS]}}, ensure_ascii=False)
        try:
            result = await self.router.generate_json("jd_scoring", SYSTEM_PROMPT, user_prompt, LLMJDScore,
                                                     max_output_tokens=200)
        except AllLLMProvidersExhaustedError:
            return None
        value = result.value
        if self.cache is not None and normalize_question(key):
            await self.cache.put(KIND, key, value.model_dump_json(), "llm")
        return JDDecision(value.match and value.score >= self.min_score, value.score, value.reason, "llm",
                          result.provider)
