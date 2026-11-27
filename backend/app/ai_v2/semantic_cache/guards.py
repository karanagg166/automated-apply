"""Poison-proof acceptance of a cache candidate.

A candidate (exact or semantic) is served only when EVERY check passes, in this order:
  inactive        status != active, or past expires_at
  scope           company-scoped entry for another company
  intent          different intent bucket
  field_type      incompatible field type (a long_text paragraph never fills a boolean/number)
  entity          tech / city / country / work-mode / employment / unit / number sets differ
                  (a mention on only one side is a difference)
  polarity        negation, opposite-intent tags or current-vs-expected differ
  cross_company   the cached answer names the company it was written for, which is not this job's
  stale_profile   factual entry whose profile_version_hash is not the candidate's current hash
  below_threshold cosine under the per-field-type floor (borderline band rejected unless verified)
  option          the cached value does not map onto exactly one live option
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.ai_v2.semantic_cache.keys import canonical_question, company_slug
from backend.app.ai_v2.semantic_cache.models import CacheEntry, QuestionContext
from backend.app.ai_v2.semantic_cache.policy import (
    CacheThresholds,
    cache_policy,
    classify_intent,
    compatible_field_types,
    infer_field_type,
    invalidation_scope,
)
from backend.app.ai_v2.semantic_cache.qualifiers import (
    ENTITY_FIELDS,
    POLARITY_FIELDS,
    Qualifiers,
    extract_qualifiers,
)

_STOPWORDS = frozenset("a an the you your do are is of in to for with on at and or have has be been this that "
                       "how what which will would can could please".split())


@dataclass(frozen=True)
class QueryProfile:
    """Everything derived once per lookup/put from the question + the caller's context."""

    kind: str
    question: str
    canonical: str
    intent: str
    field_type: str
    policy: str
    invalidation: str
    qualifiers: Qualifiers
    options: tuple[str, ...] = ()
    company: str | None = None
    company_slug: str | None = None
    profile_hash: str | None = None
    typed: bool = False  # the caller passed a QuestionContext (typed thresholds apply)
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def scope_slug(self) -> str | None:
        return self.company_slug if self.policy == "company_scoped" else None


def build_query(kind: str, question: str, context: QuestionContext | None = None) -> QueryProfile:
    ctx = context or QuestionContext()
    intent = classify_intent(question)
    policy = cache_policy(intent, question)
    return QueryProfile(
        kind=kind, question=question, canonical=canonical_question(question, ctx.company), intent=intent,
        field_type=infer_field_type(ctx.field_kind, ctx.options, question, intent=intent), policy=policy,
        invalidation=invalidation_scope(intent, policy), qualifiers=extract_qualifiers(question),
        options=tuple(ctx.options), company=ctx.company, company_slug=company_slug(ctx.company),
        profile_hash=ctx.profile_hash, typed=context is not None)


def fit_answer(answer: str, options: tuple[str, ...]) -> str | None:
    """Map a cached/LLM value onto exactly one live option (None = option_mismatch).

    Exact (normalized) option text first, then the yes/no synonym family ("Yes", "Yes, I am", "True",
    "Y" -> the single option starting with Yes)."""
    from backend.app.browser_v2.answers import choose_option, choose_yes_no

    if not options:
        return answer
    exact = choose_option(options, answer)
    if exact is not None:
        return exact
    lowered = answer.strip().lower()
    if re.match(r"^(?:yes|y|true)\b", lowered) or lowered in {"i am", "i do", "i have"}:
        return choose_yes_no(options, True)
    if re.match(r"^(?:no|n|false)\b", lowered) or lowered in {"i am not", "i do not", "i don't"}:
        return choose_yes_no(options, False)
    return None


def _entry_intent(entry: CacheEntry) -> str:
    return entry.meta.intent_bucket or classify_intent(entry.question_text)


def _entry_field_type(entry: CacheEntry, intent: str) -> str:
    return entry.meta.field_type or infer_field_type(None, (), entry.question_text, intent=intent,
                                                     answer=entry.answer_text)


def _field_type_ok(entry: CacheEntry, intent: str, wanted: str) -> bool:
    """Typed entries need a compatible type; untyped ones (pre-006 rows, owner-taught answers with no
    form context) only have to agree on long-form vs short value; the option validator does the rest."""
    if entry.meta.field_type:
        return entry.meta.field_type in compatible_field_types(wanted)
    return (_entry_field_type(entry, intent) == "long_text") == (wanted == "long_text")


def _entry_invalidation(entry: CacheEntry, intent: str) -> str:
    if entry.meta.invalidation_scope:
        return entry.meta.invalidation_scope
    return invalidation_scope(intent, "company_scoped" if entry.meta.scope == "company" else "global")


def names_other_company(answer: str, entry: CacheEntry, query: QueryProfile) -> bool:
    """The cached answer mentions the company it was written for, and this job is a different one."""
    written_for = entry.meta.company_slug or (entry.meta.entities or {}).get("company")
    if not written_for or written_for == query.company_slug:
        return False
    words = [w for w in str(written_for).split("-") if len(w) >= 3]
    if not words:
        return False
    text = f" {re.sub(r'[^a-z0-9]+', ' ', answer.lower())} "
    return all(f" {w} " in text for w in words)


def _lexically_close(query: str, cached: str) -> bool:
    left = {w for w in query.split() if w not in _STOPWORDS}
    right = {w for w in cached.split() if w not in _STOPWORDS}
    return bool(left) and left == right


def evaluate(query: QueryProfile, entry: CacheEntry, similarity: float, *, thresholds: CacheThresholds,
             base_threshold: float, now: datetime | None = None) -> tuple[str | None, str | None]:
    """(rejection decision, fitted answer). A None decision means the candidate is accepted."""
    moment = now or datetime.now(UTC)
    if entry.status != "active" or (entry.meta.expires_at is not None and entry.meta.expires_at <= moment):
        return "rejected_inactive", None
    if entry.meta.scope == "company" and entry.meta.company_slug != query.company_slug:
        return "rejected_scope", None
    if query.policy == "company_scoped" and entry.meta.scope != "company":
        return "rejected_scope", None  # motivation answers are never served from a global row
    intent = _entry_intent(entry)
    if intent != query.intent:
        return "rejected_intent", None
    if query.typed and not _field_type_ok(entry, intent, query.field_type):
        return "rejected_field_type", None
    cached_q = extract_qualifiers(entry.question_text)
    differences = query.qualifiers.differences(cached_q)
    if any(name in POLARITY_FIELDS for name in differences):
        return "rejected_polarity_flip", None
    if any(name in ENTITY_FIELDS for name in differences):
        return "rejected_entity_mismatch", None
    if names_other_company(entry.answer_text, entry, query):
        return "rejected_cross_company", None
    if query.profile_hash and _entry_invalidation(entry, intent) == "factual_profile" \
            and entry.meta.profile_version_hash != query.profile_hash:
        return "rejected_stale_profile", None
    floor = thresholds.floor(query.field_type, query.intent) if query.typed else base_threshold
    if similarity < floor:
        borderline = similarity >= floor - thresholds.band
        if not (borderline and thresholds.verify_borderline
                and _lexically_close(query.canonical, canonical_question(entry.question_text))):
            return "rejected_below_threshold", None
    fitted = fit_answer(entry.answer_text, query.options)
    if fitted is None:
        return "rejected_option_mismatch", None
    return None, fitted
