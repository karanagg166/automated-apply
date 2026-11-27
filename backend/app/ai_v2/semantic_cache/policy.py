"""Cache policy: intent buckets, field types, scope, invalidation scope and similarity thresholds.

Pure functions only (no I/O). The same classification runs when an entry is written and when a
question is looked up, so the hard prefilters (intent, field type, scope) compare like with like.

Intent buckets (crisp, regex-first, first match wins):
  sponsorship, work_authorization, relocation, notice_period, compensation, education,
  background_check, referral_source, company_motivation, role_specific_custom,
  project_experience, behavioral_general, tech_experience, other

Cache policy:
  global          reusable for every company (subject to every guard)
  company_scoped  reusable only for the same company (motivation / "why us" answers)
  never_cache     never written, never served (cover letters, coding/case prompts)

Invalidation scope:
  factual_profile    skipped when the candidate's profile_version_hash changes
  behavioral_stable  survives profile edits; TTL 180 days
  company_scoped     keyed by company_slug; TTL 30 days
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from backend.app.browser_v2.answers.classifier import (
    CURRENT_CTC,
    EXPECTED_CTC,
    HEAR_ABOUT_Q,
    IMMEDIATE_JOINER,
    JOIN_WITHIN,
    NOTICE,
    RELOCATE,
    SKILL_EXPERIENCE,
    SKILL_YES_NO,
    SPONSORSHIP_Q,
    START_WHEN,
    TOTAL_EXPERIENCE,
    WORK_AUTH_Q,
    YEARS_THRESHOLD,
)
from backend.app.browser_v2.tech_terms import tech_terms

INTENTS = ("sponsorship", "work_authorization", "relocation", "notice_period", "compensation", "education",
           "background_check", "referral_source", "company_motivation", "role_specific_custom",
           "project_experience", "behavioral_general", "tech_experience", "other")
FIELD_TYPES = ("boolean", "single_select", "multi_select", "number", "date", "short_text", "long_text")
POLICIES = ("global", "company_scoped", "never_cache")
INVALIDATION_SCOPES = ("factual_profile", "behavioral_stable", "company_scoped")
STATUSES = ("active", "quarantined", "expired")

# Facts that change when the profile changes (CTC, notice period, YoE, city, authorization, skills).
FACTUAL_INTENTS = frozenset({"sponsorship", "work_authorization", "relocation", "notice_period", "compensation",
                             "education", "tech_experience"})
# The answer depends on which country the job is in: never served without a named country.
GEO_INTENTS = frozenset({"sponsorship", "work_authorization"})
LONG_FORM_INTENTS = frozenset({"behavioral_general", "project_experience", "company_motivation"})
BEHAVIORAL_TTL = timedelta(days=180)
COMPANY_TTL = timedelta(days=30)

DEFAULT_FACTUAL_THRESHOLD = 0.93
DEFAULT_LONG_TEXT_THRESHOLD = 0.88
DEFAULT_BORDERLINE_BAND = 0.04
FACTUAL_THRESHOLD_ENV = "SEMANTIC_CACHE_THRESHOLD_FACTUAL"
LONG_TEXT_THRESHOLD_ENV = "SEMANTIC_CACHE_THRESHOLD_LONG_TEXT"
BORDERLINE_BAND_ENV = "SEMANTIC_CACHE_BORDERLINE_BAND"
BORDERLINE_VERIFY_ENV = "SEMANTIC_CACHE_BORDERLINE_VERIFY"

_I = re.IGNORECASE
BACKGROUND_CHECK = re.compile(r"\bbackground (?:check|verification|screening)\b|\bcriminal\b|\bconvicted\b|"
                              r"\bdrug (?:test|screen)\b|\bfelony\b", _I)
REFERRAL = re.compile(r"\breferr(?:ed|al)\b|\bwho referred\b|\bemployee referral\b", _I)
EDUCATION = re.compile(r"\b(?:degree|bachelor'?s?|master'?s?|b\.?\s?tech|m\.?\s?tech|b\.?e\b|graduat\w*|"
                       r"cgpa|gpa|university|college|highest (?:level of )?(?:education|qualification)|"
                       r"diploma|percentage in|10th|12th|backlogs?)\b", _I)
COMPENSATION = re.compile(r"\b(?:salary|compensation|ctc|stipend|pay|remuneration|package|lpa|wage)\b", _I)
MOTIVATION = re.compile(
    r"\bwhy (?:do you want|are you (?:interested|applying|excited)|would you like|should we hire|us\b|"
    r"this (?:company|role|position|team)|join|work (?:here|with us|for us|at))|"
    r"\bwhat (?:excites|interests|attracts|draws) you\b|\binterest(?:ed)? in (?:joining|working at|this company)\b|"
    r"\bcover (?:letter|note)\b|\bwhat do you know about (?:us|our)\b|\bour (?:mission|product|company)\b", _I)
CUSTOM_PROMPT = re.compile(
    r"\b(?:write (?:a |an )?(?:function|program|query|code|sql)|solve|implement|case study|take.?home|"
    r"assignment|how would you (?:design|build|architect|implement)|system design|leetcode|"
    r"github link to (?:the|your) (?:solution|assignment)|link to (?:the|your) (?:solution|assignment))\b", _I)
COVER_LETTER = re.compile(r"\bcover (?:letter|note)\b", _I)
PROJECT = re.compile(r"\b(?:describe|tell (?:us|me) about|share|walk (?:us|me) through)\b.*\bproject\b|"
                     r"\bproject (?:you|that you|which you)\b|\bmost (?:challenging|complex|impressive)\b.*"
                     r"\b(?:project|thing|system) you\b", _I)
BEHAVIORAL = re.compile(r"\btell (?:us|me) about (?:a time|yourself)\b|\bdescribe (?:a time|a situation|yourself)\b|"
                        r"\b(?:strengths?|weakness(?:es)?|conflict|failure|challenge you|introduce yourself)\b|"
                        r"\bwhere do you see yourself\b|\bwhat motivates you\b", _I)
NUMBER_Q = re.compile(r"\bhow many\b|\b(?:number of|years of|no\.? of)\b|\bin years\b|\b\(years?\)", _I)
DATE_Q = re.compile(r"\b(?:date|dob|when (?:did|will) you)\b", _I)
YES_NO_OPTION = re.compile(r"^\s*(?:yes|no|y|n|true|false)\b", _I)


def classify_intent(question: str) -> str:
    """Crisp intent bucket for one screening question (first matching rule wins)."""
    text = question or ""
    if SPONSORSHIP_Q.search(text) or re.search(r"\bvisa\b", text, _I):
        return "sponsorship"
    if WORK_AUTH_Q.search(text) or re.search(r"\b(?:citizen(?:ship)?|green card|work visa)\b", text, _I):
        return "work_authorization"
    if CUSTOM_PROMPT.search(text):
        return "role_specific_custom"
    if MOTIVATION.search(text):
        return "company_motivation"
    if NOTICE.search(text) or START_WHEN.search(text) or IMMEDIATE_JOINER.search(text) or JOIN_WITHIN.search(text):
        return "notice_period"
    if CURRENT_CTC.search(text) or EXPECTED_CTC.search(text) or COMPENSATION.search(text):
        return "compensation"
    if RELOCATE.search(text) or re.search(r"\b(?:currently (?:located|based|living|residing)|commute|"
                                          r"willing to (?:move|work from|travel))\b", text, _I):
        return "relocation"
    if BACKGROUND_CHECK.search(text):
        return "background_check"
    if HEAR_ABOUT_Q.search(text) or REFERRAL.search(text):
        return "referral_source"
    if EDUCATION.search(text):
        return "education"
    if PROJECT.search(text):
        return "project_experience"
    if BEHAVIORAL.search(text):
        return "behavioral_general"
    if YEARS_THRESHOLD.search(text) or TOTAL_EXPERIENCE.search(text) or tech_terms(text) \
            or SKILL_EXPERIENCE.search(text) or SKILL_YES_NO.search(text):
        return "tech_experience"
    return "other"


def _yes_no_options(options: tuple[str, ...]) -> bool:
    return bool(options) and len(options) <= 3 and all(YES_NO_OPTION.match(o) for o in options)


_KIND_TYPES = {"textarea": "long_text", "number": "number", "date": "date", "multi": "multi_select",
               "multi_select": "multi_select", "boolean": "boolean"}


def infer_field_type(field_kind: str | None, options: tuple[str, ...], question: str, *,
                     intent: str | None = None, answer: str | None = None) -> str:
    """Normalized field type. `field_kind` is the DOM/HITL kind when known (radio, select,
    combobox, checkbox, textarea, text, number, date, multi, choice); otherwise options, the
    question's intent and (for legacy cache rows) the stored answer's shape decide."""
    kind = (field_kind or "").strip().lower()
    if kind in FIELD_TYPES:
        return kind
    if kind in _KIND_TYPES:
        return _KIND_TYPES[kind]
    if options:
        if _yes_no_options(options):
            return "boolean"
        return "multi_select" if kind == "checkbox" else "single_select"
    if kind == "checkbox":
        return "boolean"
    intent = intent or classify_intent(question)
    if intent in LONG_FORM_INTENTS:
        return "long_text"
    if answer is not None:
        stripped = answer.strip()
        if YES_NO_OPTION.fullmatch(stripped) or stripped.lower() in {"yes", "no"}:
            return "boolean"
        if re.fullmatch(r"[\d.]+", stripped):
            return "number"
        if len(stripped) > 160:
            return "long_text"
    if NUMBER_Q.search(question or "") and kind != "text":
        return "number"
    return "short_text"


# boolean <-> single_select: a radio "Yes/No" and a select "Yes/No" are the same field; the
# option-set validator still has to map the cached value onto the live options.
_COMPATIBLE = {"boolean": frozenset({"boolean", "single_select"}),
               "single_select": frozenset({"single_select", "boolean"})}


def compatible_field_types(field_type: str) -> frozenset[str]:
    return _COMPATIBLE.get(field_type, frozenset({field_type}))


def cache_policy(intent: str, question: str) -> str:
    if intent == "role_specific_custom" or COVER_LETTER.search(question or ""):
        return "never_cache"
    if intent == "company_motivation":
        return "company_scoped"
    return "global"


def invalidation_scope(intent: str, policy: str) -> str:
    if policy == "company_scoped":
        return "company_scoped"
    return "factual_profile" if intent in FACTUAL_INTENTS else "behavioral_stable"


def ttl_for(scope: str) -> timedelta | None:
    return {"behavioral_stable": BEHAVIORAL_TTL, "company_scoped": COMPANY_TTL}.get(scope)


@dataclass(frozen=True)
class CacheThresholds:
    """Per field type cosine floors. Anything below the floor is a miss; [floor - band, floor) is the
    borderline zone, rejected unless the lexical verifier is enabled and agrees."""

    factual: float = DEFAULT_FACTUAL_THRESHOLD
    long_text: float = DEFAULT_LONG_TEXT_THRESHOLD
    band: float = DEFAULT_BORDERLINE_BAND
    verify_borderline: bool = False

    def floor(self, field_type: str, intent: str) -> float:
        return self.long_text if field_type == "long_text" or intent in LONG_FORM_INTENTS else self.factual

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None, *, long_text: float | None = None) -> CacheThresholds:
        env = env or {}

        def number(name: str, default: float, low: float, high: float) -> float:
            try:
                value = float(env.get(name) or default)
            except ValueError:
                return default
            return value if low <= value <= high else default

        base_long = long_text if long_text is not None else DEFAULT_LONG_TEXT_THRESHOLD
        return cls(factual=number(FACTUAL_THRESHOLD_ENV, DEFAULT_FACTUAL_THRESHOLD, 0.80, 1.0),
                   long_text=number(LONG_TEXT_THRESHOLD_ENV, base_long, 0.75, 1.0),
                   band=number(BORDERLINE_BAND_ENV, DEFAULT_BORDERLINE_BAND, 0.0, 0.10),
                   verify_borderline=(env.get(BORDERLINE_VERIFY_ENV) or "").strip().lower() == "lexical")
