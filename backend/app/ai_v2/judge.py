"""LLM-as-judge: a second free model audits every LLM screening answer before it is used.

The generator (Tier 2 of `ScreeningAnswerer`) answers from the PII-free profile; the judge is a
different provider family that sees the same profile, the question, the options and the answer
and decides whether the answer is fully supported by the profile. The verdict is written to the
generator's Langfuse trace as scores (`judge_supported`, `judge_score`), so agreement rate and
every rejected answer are reviewable in one place.

AI_V2_JUDGE_MODE:
  off      never call the judge.
  shadow   (default) judge only when Langfuse tracing is on; the answer is still used, the
           verdict is scored. A rejected answer is never written to the semantic cache.
  enforce  judge always; a rejected answer is dropped and the question goes to the human (HITL).

Fail-open: if no other provider can judge (quota, outage), the answer is handled exactly as it
was before this module existed. The judge can only ever make the pipeline more conservative.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter

logger = logging.getLogger(__name__)

TASK = "answer_judge"
MODE_ENV = "AI_V2_JUDGE_MODE"
MODES = ("off", "shadow", "enforce")
DEFAULT_MODE = "shadow"
MIN_SUPPORT_SCORE = 0.70

SYSTEM_PROMPT = (
    "You audit an answer that another assistant wrote for a job-application screening question. "
    "You are given the candidate profile JSON, the question, the allowed options (may be empty) and "
    "the proposed answer. Judge ONLY against the profile. Set supported=false when the answer states "
    "or implies any fact that is not in the profile (dates, employers, years of experience, "
    "compensation, certifications, work authorization, links), contradicts the profile, does not "
    "actually answer the question, or is not one of the options when options are given. Set "
    "supported=true only when every claim in the answer follows from the profile. score is your "
    "confidence from 0 to 1 that the answer is correct and truthful for this candidate. Reply with "
    'one JSON object: {"supported": boolean, "score": number 0-1, "reason": string under 200 characters}.')


class JudgeReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    supported: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


@dataclass(frozen=True)
class JudgeVerdict:
    approved: bool
    score: float
    reason: str
    provider: str
    model: str

    @property
    def label(self) -> str:
        return "approved" if self.approved else "rejected"


def judge_mode(env: Mapping[str, str]) -> str:
    value = (env.get(MODE_ENV) or DEFAULT_MODE).strip().lower()
    return value if value in MODES else DEFAULT_MODE


class AnswerJudge:
    def __init__(self, router: LLMRouter, *, mode: str = DEFAULT_MODE,
                 min_score: float = MIN_SUPPORT_SCORE) -> None:
        self.router = router
        self.mode = mode if mode in MODES else DEFAULT_MODE
        self.min_score = min_score

    @property
    def enforce(self) -> bool:
        return self.mode == "enforce"

    @property
    def active(self) -> bool:
        if self.mode == "enforce":
            return True
        return self.mode == "shadow" and bool(getattr(self.router.tracer, "enabled", False))

    async def review(self, *, question: str, options: tuple[str, ...], answer: str,
                     safe_profile: Mapping[str, Any], job: Mapping[str, Any], generator: str,
                     trace_id: str | None = None) -> JudgeVerdict | None:
        """None = no verdict (judge off, or no other provider available): caller fails open."""
        if not self.active:
            return None
        prompt = json.dumps({"candidate_profile": dict(safe_profile), "job": dict(job), "question": question,
                             "options": list(options), "proposed_answer": answer}, ensure_ascii=False)
        try:
            result = await self.router.generate_json(TASK, SYSTEM_PROMPT, prompt, JudgeReply,
                                                     max_output_tokens=200, exclude=(generator,))
        except AllLLMProvidersExhaustedError:
            self.router.tracer.score(trace_id, "judge_available", False, comment="no_other_provider")
            return None
        except Exception as exc:  # noqa: BLE001 - the judge must never break answering
            logger.warning("answer_judge_failed: %s", type(exc).__name__)
            return None
        reply = result.value
        verdict = JudgeVerdict(reply.supported and reply.score >= self.min_score, reply.score, reply.reason,
                               result.provider, result.model)
        comment = f"{verdict.provider}/{verdict.model}: {verdict.reason}"[:480]
        self.router.tracer.score(trace_id, "judge_supported", verdict.approved, comment=comment)
        self.router.tracer.score(trace_id, "judge_score", verdict.score, comment=comment)
        logger.info("answer_judge verdict=%s score=%.2f generator=%s judge=%s mode=%s", verdict.label,
                    verdict.score, generator, verdict.provider, self.mode)
        return verdict
