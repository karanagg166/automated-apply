"""Evidence-bound project records, deterministic compaction and review contracts."""

import re
from typing import Literal, Protocol

from pydantic import Field, model_validator

from backend.app.candidate_context.common import ContextError, Contract, canonical_hash
from backend.app.candidate_context.configuration import ProjectConfiguration
from backend.app.core.urls import PublicHTTPSURL

FactTopic = Literal[
    "overview",
    "business_use_case",
    "architecture",
    "frontend",
    "backend",
    "database",
    "cache",
    "queue",
    "authentication_security",
    "deployment",
    "api",
    "challenge",
    "contribution",
    "feature",
    "design_decision",
    "measured_outcome",
    "interview",
    "technology",
]


class EvidenceReference(Contract):
    file: str = Field(min_length=1, max_length=240)
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_start: int = Field(default=1, ge=1, le=100000)
    line_end: int = Field(default=1, ge=1, le=100000)
    url: PublicHTTPSURL | None = None

    @model_validator(mode="after")
    def safe_reference(self):
        if (
            self.file.startswith(("/", "\\"))
            or ".." in self.file.split("/")
            or "\\" in self.file
        ):
            raise ValueError("relative_evidence_path_required")
        if self.line_end < self.line_start:
            raise ValueError("invalid_evidence_lines")
        return self


class ProjectFact(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    topic: FactTopic
    text: str = Field(min_length=1, max_length=2000)
    verification: Literal["direct", "owner_supplied", "inferred"]
    evidence: tuple[EvidenceReference, ...] = Field(default=(), max_length=10)
    technology: str | None = Field(default=None, min_length=1, max_length=60)
    personal_claim: bool = False

    @property
    def approvable(self) -> bool:
        return (
            bool(self.evidence)
            and self.verification != "inferred"
            and (not self.personal_claim or self.verification == "owner_supplied")
            and not suspicious_text(self.text)
        )


def suspicious_text(text: str) -> bool:
    return bool(
        re.search(
            r"ignore.{0,60}(?:instruction|prompt)|system\s+(?:prompt|message)|"
            r"(?:run|execute)\s+(?:shell|command|sql)|(?:reveal|print|export).{0,30}(?:token|password|secret)|"
            r"(?:sk-[A-Za-z0-9_-]{12,}|sbp_[A-Za-z0-9_-]{12,}|\d{6,}:[A-Za-z0-9_-]{20,})",
            text,
            re.I | re.S,
        )
    )


def compact(text: str, *, max_words: int, max_characters: int) -> str:
    if not 1 <= max_words <= 1000 or not 1 <= max_characters <= 10000:
        raise ContextError("invalid_compaction_limit")
    value = " ".join(text.split()[:max_words])
    if len(value) > max_characters:
        value = value[:max_characters]
        if " " in value:
            value = value.rsplit(" ", 1)[0]
    return value


class CompactContexts(Contract):
    overview_50: str
    explanation_100: str
    architecture: str
    technology_stack: str
    engineering_challenges: str
    interview_explanation: str
    resume_bullet_candidates: tuple[str, ...]
    fact_ids: tuple[str, ...]
    generator: Literal["deterministic_extractive"] = "deterministic_extractive"


def contexts(facts: tuple[ProjectFact, ...]) -> CompactContexts:
    # Callers explicitly decide candidate/approved facts. Never add connective
    # claims such as "I built", business impact, scale or responsibility.
    def text(topics):
        return " ".join(fact.text for fact in facts if fact.topic in topics)

    overview = text({"overview", "business_use_case", "feature", "contribution"})
    technical = text(
        {
            "architecture",
            "frontend",
            "backend",
            "database",
            "cache",
            "queue",
            "authentication_security",
            "deployment",
            "api",
            "design_decision",
        }
    )
    stack = text({"technology"})
    base = overview or technical or stack
    compress = lambda value, words=100, chars=2000: compact(
        value, max_words=words, max_characters=chars
    )
    return CompactContexts(
        overview_50=compress(base, 50),
        explanation_100=compress(base),
        architecture=compress(technical),
        technology_stack=compress(stack),
        engineering_challenges=compress(text({"challenge"})),
        interview_explanation=compress(
            text({"interview", "contribution", "challenge"}) or base
        ),
        resume_bullet_candidates=tuple(
            compress(fact.text, 35, 240)
            for fact in facts
            if fact.topic in {"contribution", "feature", "measured_outcome"}
        )[:5],
        fact_ids=tuple(fact.id for fact in facts),
    )


class ProjectSnapshot(Contract):
    configuration: ProjectConfiguration
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    facts: tuple[ProjectFact, ...] = Field(max_length=100)
    unsupported_stack_claims: tuple[str, ...] = ()
    candidate_contexts: CompactContexts
    last_verified_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    status: Literal["pending_review"] = "pending_review"


class ProjectApproval(Contract):
    project_id: str
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    fact_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    owner_ref: str = Field(min_length=1, max_length=120)
    approved_at: str
    facts: tuple[ProjectFact, ...]
    contexts: CompactContexts
    status: Literal["approved"] = "approved"


class RewriteRequest(Contract):
    question: str = Field(min_length=1, max_length=2000)
    facts: tuple[ProjectFact, ...] = Field(max_length=100)
    max_words: int = Field(default=100, ge=1, le=500)
    max_characters: int = Field(default=2000, ge=1, le=8000)


class RewriteResult(Contract):
    text: str = Field(max_length=8000)
    fact_ids: tuple[str, ...]
    generator: str = Field(min_length=1, max_length=80)


class ApprovedRewriter(Protocol):
    """Future model adapter: no tools, no authority, approved facts only.

    Rewriters remain opt-in and results need semantic review. No LLM implementation
    or invocation is bundled; deterministic extraction is the default.
    """

    async def rewrite(self, request: RewriteRequest) -> RewriteResult: ...


def make_fact(
    topic: FactTopic,
    text: str,
    verification: Literal["direct", "owner_supplied", "inferred"],
    evidence: tuple[EvidenceReference, ...],
    *,
    technology=None,
    personal_claim=False,
) -> ProjectFact:
    value = {
        "topic": topic,
        "text": text,
        "verification": verification,
        "evidence": [ref.model_dump(mode="json") for ref in evidence],
        "technology": technology,
        "personal_claim": personal_claim,
    }
    return ProjectFact(id=canonical_hash(value), **value)
