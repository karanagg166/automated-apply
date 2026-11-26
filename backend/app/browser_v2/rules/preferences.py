"""Candidate preference filters (candidate_profiles.preferences)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.app.browser_v2.rules.decision import (
    TITLE_MISMATCH_PREFIX,
    Decision,
    FilterResult,
)
from backend.app.browser_v2.rules.normalize import (
    _ROLE_STOPWORDS,
    _role_matches,
    contains_term,
    normalize_company,
    normalize_role,
    normalize_text,
)
from backend.app.browser_v2.rules.parsing import (
    parse_experience_range,
    parse_salary_lpa,
)

# --- Candidate preference filters (candidate_profiles.preferences) -----------------

@dataclass(frozen=True)
class CandidatePreferences:
    target_roles: tuple[str, ...] = ()
    keywords_required: tuple[str, ...] = ()
    keywords_excluded: tuple[str, ...] = ()
    tech_stack: tuple[str, ...] = ()
    company_blacklist: tuple[str, ...] = ()
    remote_policy: str = "any"
    min_ctc: float | None = None
    skill_match_mode: str = "any"
    experience_years: float | None = None  # Phase 8b: total experience (preferences or verified)
    max_required_experience_years: float | None = None  # Phase 9B: hard ceiling on a job's minimum

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> CandidatePreferences:
        prefs = profile.get("preferences") or {}

        def strings(*keys: str) -> tuple[str, ...]:
            values: list[str] = []
            for key in keys:
                for item in prefs.get(key) or []:
                    if isinstance(item, str) and item.strip() and item.strip() not in values:
                        values.append(item.strip())
            return tuple(values)

        min_ctc = prefs.get("min_ctc")
        return cls(
            target_roles=strings("target_roles", "target_titles"),  # dashboard schema stores target_titles
            keywords_required=strings("keywords_required"),
            keywords_excluded=strings("keywords_excluded"),
            tech_stack=strings("tech_stack"),
            company_blacklist=strings("company_blacklist"),
            remote_policy=str(prefs.get("remote_policy") or "any"),
            min_ctc=float(min_ctc) if isinstance(min_ctc, (int, float)) and not isinstance(min_ctc, bool)
            else None,
            skill_match_mode=str(prefs.get("skill_match_mode") or "any"),
            experience_years=_years(prefs.get("total_experience_years"), profile.get("verified_experience_years")),
            max_required_experience_years=_years(prefs.get("max_required_experience_years")),
        )


def _years(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            return float(value)
    return None


EXPERIENCE_TOLERANCE_YEARS = 1.0


def evaluate_experience(experience_text: str | None, prefs: CandidatePreferences) -> FilterResult:
    """Skip roles whose MINIMUM experience is beyond the candidate's (+1 year tolerance), or beyond
    the owner's explicit `max_required_experience_years` ceiling when set (no tolerance)."""
    low, high = parse_experience_range(experience_text)
    if low is None:
        return FilterResult(Decision.PASS)
    shown = f"{low:g}-{high:g}" if high is not None else f"{low:g}+"
    if prefs.max_required_experience_years is not None:
        if low > prefs.max_required_experience_years:
            return FilterResult(Decision.FILTERED, (
                f"experience_above_max: needs {shown} yrs, max {prefs.max_required_experience_years:g}",))
        return FilterResult(Decision.PASS)
    if prefs.experience_years is None:
        return FilterResult(Decision.PASS)
    if low > prefs.experience_years + EXPERIENCE_TOLERANCE_YEARS:
        return FilterResult(Decision.FILTERED,
                            (f"experience_above_profile: needs {shown} yrs, have {prefs.experience_years:g}",))
    return FilterResult(Decision.PASS)


def evaluate_preferences(*, title: str | None, company: str | None, description: str | None,
                         salary_text: str | None, work_mode: str | None,
                         prefs: CandidatePreferences, require_description: bool = False) -> FilterResult:
    """Deterministic candidate-preference filter with human-readable reasons.

    `require_description=False` runs only the checks that the search card can
    answer (company/title); required keywords and tech stack wait for the JD.
    """
    company_norm = normalize_company(company)
    company_text = normalize_text(company)
    for blocked in prefs.company_blacklist:
        blocked_norm = normalize_company(blocked)
        if blocked_norm and (blocked_norm == company_norm or contains_term(company_text, blocked)):
            return FilterResult(Decision.FILTERED, (f"company_blacklisted: {blocked}",))
    title_text = normalize_text(title)
    full_text = f"{title_text} {normalize_text(description)}".strip()
    for word in prefs.keywords_excluded:
        if contains_term(title_text, word):
            return FilterResult(Decision.FILTERED, (f"excluded_keyword_in_title: {word}",))
        if description and contains_term(full_text, word):
            return FilterResult(Decision.FILTERED, (f"excluded_keyword_in_description: {word}",))
    if prefs.target_roles and title and not any(_role_matches(title, role) for role in prefs.target_roles):
        return FilterResult(Decision.FILTERED, (f"{TITLE_MISMATCH_PREFIX}: {title}",))
    salary = parse_salary_lpa(salary_text)
    if prefs.min_ctc is not None and salary and salary.maximum_lpa is not None \
            and salary.maximum_lpa < prefs.min_ctc:
        return FilterResult(Decision.FILTERED,
                            (f"salary_below_min_ctc: max {salary.maximum_lpa:g} LPA < {prefs.min_ctc:g} LPA",))
    if prefs.remote_policy == "remote_only" and work_mode and not re.search(r"remote|work from home|wfh",
                                                                           work_mode, re.IGNORECASE):
        return FilterResult(Decision.FILTERED, (f"not_remote: {work_mode}",))
    if not require_description:
        return FilterResult(Decision.PASS)
    if not description:
        return FilterResult(Decision.PASS, ("description_unavailable_keyword_checks_skipped",))
    missing = [word for word in prefs.keywords_required if not contains_term(full_text, word)]
    if prefs.keywords_required:
        all_mode = prefs.skill_match_mode == "all"
        if (all_mode and missing) or (not all_mode and len(missing) == len(prefs.keywords_required)):
            return FilterResult(Decision.FILTERED,
                                ("required_keywords_missing: " + ", ".join(missing),))
    if prefs.tech_stack and not any(contains_term(full_text, tech) for tech in prefs.tech_stack):
        return FilterResult(Decision.FILTERED, ("no_tech_stack_overlap: " + ", ".join(prefs.tech_stack),))
    return FilterResult(Decision.PASS)


def title_gray_zone(title: str | None, prefs: CandidatePreferences) -> bool:
    """Title fails the strict target-role match but shares a meaningful role word with one
    (e.g. target "Backend Engineer" vs "Software Engineer"): eligible for the LLM tie-breaker."""
    if not title or not prefs.target_roles or any(_role_matches(title, r) for r in prefs.target_roles):
        return False
    synonyms = {"developer": {"developer", "engineer", "programmer"},
                "engineer": {"engineer", "developer", "programmer"},
                "programmer": {"programmer", "developer", "engineer"}}
    title_words = set(normalize_role(title).split()) - _ROLE_STOPWORDS
    for role in prefs.target_roles:
        for word in set(normalize_role(role).split()) - _ROLE_STOPWORDS:
            if title_words & synonyms.get(word, {word}):
                return True
    return False
