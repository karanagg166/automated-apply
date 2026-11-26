"""Per-portal rules (public.portal_rules) and deterministic job filters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any

from backend.app.browser_v2.portals import PORTALS


class ApplicantPolicy(StrEnum):
    ALLOW_LOWER_BOUND = "allow_lower_bound"
    ALLOW = "allow"
    SKIP = "skip"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PortalRules:
    platform: str
    enabled: bool = False
    auto_apply_enabled: bool = False
    max_applies_per_day: int = 50
    max_applies_per_hour: int = 10
    max_job_age_days: int = 7
    max_applicants: int = 300
    unknown_applicants_policy: ApplicantPolicy = ApplicantPolicy.ALLOW_LOWER_BOUND
    min_delay_sec: int = 45
    max_delay_sec: int = 150
    active_hours_start: time | None = time(8, 0)
    active_hours_end: time | None = time(23, 30)
    timezone: str = "Asia/Kolkata"
    auth_status: str = "UNKNOWN"
    revision: int = 1
    auth_checked_at: datetime | None = None
    portal_limit_hit_at: datetime | None = None
    updated_at: datetime | None = None
    # Phase 6A (dashboard-editable). None = a pre-6A row: env/default caps apply.
    quota_fallback_daily_cap: int | None = None
    quota_drafts_per_cycle: int | None = None
    paused_until: datetime | None = None  # temporary owner pause (agent / dashboard)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalRules:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in dict(row).items() if k in known}
        if "unknown_applicants_policy" in values:
            values["unknown_applicants_policy"] = ApplicantPolicy(values["unknown_applicants_policy"])
        return cls(**values)


# Owner-editable columns (dashboard PATCH). auth_status/revision are system-managed.
EDITABLE_RULE_FIELDS = (
    "enabled", "auto_apply_enabled", "max_applies_per_day", "max_applies_per_hour",
    "max_job_age_days", "max_applicants", "unknown_applicants_policy", "min_delay_sec",
    "max_delay_sec", "active_hours_start", "active_hours_end", "timezone",
    "quota_fallback_daily_cap", "quota_drafts_per_cycle", "paused_until",
)
DEFAULT_QUOTA_FALLBACK_DAILY_CAP = 10
DEFAULT_QUOTA_DRAFTS_PER_CYCLE = 5


def paused(rules: PortalRules, now: datetime) -> bool:
    return rules.paused_until is not None and rules.paused_until > now


def within_active_hours(rules: PortalRules, now: datetime) -> bool:
    """Active window in the portal timezone; supports windows that cross midnight."""
    from zoneinfo import ZoneInfo

    if rules.active_hours_start is None or rules.active_hours_end is None:
        return True
    local = now.astimezone(ZoneInfo(rules.timezone)).time().replace(tzinfo=None)
    start, end = rules.active_hours_start, rules.active_hours_end
    if start == end:
        return True
    if start < end:
        return start <= local < end
    return local >= start or local < end


# Mirrors the migration 004 seed: all 10 portals, only naukri enabled by default.
DEFAULT_RULES = {name: PortalRules(platform=name, enabled=info.default_enabled)
                 for name, info in PORTALS.items()}


@dataclass(frozen=True)
class ApplicantCount:
    minimum: int | None
    maximum: int | None
    is_lower_bound: bool
    raw: str | None = None

    @property
    def known(self) -> bool:
        return self.minimum is not None


UNKNOWN_APPLICANTS = ApplicantCount(None, None, True, None)
_NUMBER = re.compile(r"\d[\d,]*")


def parse_applicants(text: str | None) -> ApplicantCount:
    """Parse Naukri applicant labels. "100+" is a lower bound of 100."""
    if not text:
        return UNKNOWN_APPLICANTS
    raw = " ".join(text.split())
    lowered = raw.lower()
    numbers = [int(n.replace(",", "")) for n in _NUMBER.findall(lowered)]
    if not numbers:
        return ApplicantCount(None, None, True, raw)
    if re.search(r"\b(?:less|fewer) than\b", lowered):
        return ApplicantCount(0, max(numbers[0] - 1, 0), False, raw)
    if len(numbers) >= 2 and re.search(r"\d\s*(?:-|–|to)\s*\d", lowered):
        return ApplicantCount(numbers[0], numbers[1], False, raw)
    if "+" in lowered or re.search(r"\b(?:over|more than)\b", lowered):
        return ApplicantCount(numbers[0], None, True, raw)
    return ApplicantCount(numbers[0], numbers[0], False, raw)


_AGE_UNITS = {"hour": 0, "minute": 0, "second": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def parse_posted_age_days(text: str | None, *, today: date | None = None) -> int | None:
    """"Just now"/"Today" -> 0, "3 days ago" -> 3, "30+ days ago" -> 30, ISO date -> delta."""
    if not text:
        return None
    lowered = " ".join(text.lower().split())
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})", lowered)
    if iso:
        posted = date.fromisoformat(iso.group(1))
        return max(((today or datetime.now(UTC).date()) - posted).days, 0)
    if re.search(r"\b(just now|today|few hours|an hour|hours? ago|minutes? ago)\b", lowered):
        return 0
    if "yesterday" in lowered:
        return 1
    match = re.search(r"(\d+)\s*\+?\s*(second|minute|hour|day|week|month|year)s?", lowered)
    if match:
        return int(match.group(1)) * _AGE_UNITS[match.group(2)]
    match = re.search(r"\b(?:a|an|one)\s+(day|week|month|year)\b", lowered)
    if match:
        return _AGE_UNITS[match.group(1)]
    return None


class Decision(StrEnum):
    PASS = "pass"
    FILTERED = "filtered"
    REVIEW = "review"


@dataclass(frozen=True)
class FilterResult:
    decision: Decision
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.decision is Decision.PASS


def evaluate_applicants(count: ApplicantCount, rules: PortalRules) -> FilterResult:
    if count.known and not count.is_lower_bound:
        if count.maximum is not None and count.maximum <= rules.max_applicants:
            return FilterResult(Decision.PASS)
        return FilterResult(Decision.FILTERED, ("applicants_over_limit",))
    policy = rules.unknown_applicants_policy
    if policy is ApplicantPolicy.ALLOW:
        return FilterResult(Decision.PASS, ("applicants_upper_bound_unknown_allowed",))
    if policy is ApplicantPolicy.SKIP:
        return FilterResult(Decision.FILTERED, ("applicants_upper_bound_unknown_skipped",))
    if policy is ApplicantPolicy.NEEDS_REVIEW:
        return FilterResult(Decision.REVIEW, ("applicants_upper_bound_unknown_review",))
    lower = count.minimum or 0
    if lower <= rules.max_applicants:
        return FilterResult(Decision.PASS, ("applicants_lower_bound_used",))
    return FilterResult(Decision.FILTERED, ("applicants_over_limit",))


def evaluate_job(*, age_days: int | None, applicants: ApplicantCount, rules: PortalRules,
                 age_is_lower_bound: bool = False) -> FilterResult:
    """Deterministic pre-apply filter. Unknown age is held for review."""
    if not rules.enabled:
        return FilterResult(Decision.FILTERED, ("portal_disabled",))
    if age_days is None:
        return FilterResult(Decision.REVIEW, ("posting_age_unknown",))
    if age_days > rules.max_job_age_days or (age_is_lower_bound and age_days >= rules.max_job_age_days):
        return FilterResult(Decision.FILTERED, ("posting_too_old",))
    return evaluate_applicants(applicants, rules)


# --- Candidate preference filters (candidate_profiles.preferences) -----------------

_COMPANY_SUFFIX = re.compile(
    r"\b(?:private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|co|company|"
    r"technologies|technology|tech|solutions|software|services|india|global|labs?)\b\.?", re.IGNORECASE)
_WORDS = re.compile(r"[a-z0-9+#]+(?:\.[a-z0-9]+)*")


def normalize_text(value: str | None) -> str:
    return " ".join(_WORDS.findall((value or "").lower()))


def normalize_company(value: str | None) -> str:
    core = normalize_text(_COMPANY_SUFFIX.sub(" ", value or ""))
    return core or normalize_text(value)


def normalize_role(value: str | None) -> str:
    text = normalize_text(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", value or ""))
    replacements = {"sr": "senior", "jr": "junior", "engg": "engineer", "dev": "developer",
                    "swe": "software engineer", "sde": "software development engineer"}
    return " ".join(replacements.get(word, word) for word in text.split())


DEDUP_PART_MAX = 160  # live 2026-11-26: wellfound card text overflowed the btree index (2704-byte limit)


def dedup_key(company: str | None, title: str | None) -> str | None:
    """Cross-portal identity: normalized `company::role`, each part bounded (deterministic)."""
    company_key, role_key = normalize_company(company), normalize_role(title)
    if not company_key or not role_key:
        return None
    return f"{company_key[:DEDUP_PART_MAX].strip()}::{role_key[:DEDUP_PART_MAX].strip()}"


def contains_term(haystack: str, term: str) -> bool:
    """Whole-word, case-insensitive match on normalized text ("go" does not match "google")."""
    needle = normalize_text(term)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9+#]){re.escape(needle)}(?![a-z0-9+#])", haystack) is not None


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
        )


@dataclass(frozen=True)
class SalaryRange:
    minimum_lpa: float | None
    maximum_lpa: float | None


_SALARY_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_salary_lpa(text: str | None) -> SalaryRange | None:
    """"8-12 Lacs PA" -> (8, 12); "₹ 8,00,000 - 12,00,000" -> (8, 12); "Not disclosed" -> None."""
    if not text or re.search(r"not disclosed|undisclosed|competitive|as per", text, re.IGNORECASE):
        return None
    lowered = text.lower()
    if re.search(r"per month|/\s*month|monthly|\bpm\b", lowered):
        return None
    numbers = [float(n.replace(",", "")) for n in _SALARY_NUMBER.findall(lowered)]
    if not numbers:
        return None
    if re.search(r"\bcr(?:ore)?s?\b", lowered):
        numbers = [n * 100 for n in numbers]
    elif not re.search(r"lakh|lac|lpa|\bl\b", lowered):
        numbers = [n / 100_000 if n >= 1000 else n for n in numbers]
    low, high = numbers[0], numbers[1] if len(numbers) > 1 else numbers[0]
    return SalaryRange(min(low, high), max(low, high))


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


_ROLE_STOPWORDS = frozenset({"senior", "junior", "lead", "staff", "principal", "associate", "intern",
                             "i", "ii", "iii", "iv", "sr", "jr", "the", "a", "an", "and", "of", "for", "in"})


def _role_matches(title: str, role: str) -> bool:
    """Every meaningful word of the target role appears in the title (seniority-insensitive)."""
    title_words = set(normalize_role(title).split())
    words = [w for w in normalize_role(role).split() if w not in _ROLE_STOPWORDS]
    synonyms = {"developer": {"developer", "engineer", "programmer"},
                "engineer": {"engineer", "developer", "programmer"},
                "backend": {"backend", "back"}, "frontend": {"frontend", "front"},
                "fullstack": {"fullstack", "full"}}
    return bool(words) and all(title_words & synonyms.get(w, {w}) for w in words)


TITLE_MISMATCH_PREFIX = "title_not_in_target_roles"


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


def is_title_mismatch_only(result: FilterResult) -> bool:
    return result.decision is Decision.FILTERED and len(result.reasons) == 1 \
        and result.reasons[0].startswith(TITLE_MISMATCH_PREFIX)


def evaluate_pipeline(*, age_days: int | None, applicants: ApplicantCount, rules: PortalRules,
                      prefs: CandidatePreferences, title: str | None, company: str | None,
                      description: str | None = None, salary_text: str | None = None,
                      work_mode: str | None = None, age_is_lower_bound: bool = False,
                      require_description: bool = True) -> FilterResult:
    """Portal hard filters (age, applicants) then candidate preferences."""
    portal = evaluate_job(age_days=age_days, applicants=applicants, rules=rules,
                          age_is_lower_bound=age_is_lower_bound)
    if portal.decision is Decision.FILTERED:
        return portal
    preference = evaluate_preferences(title=title, company=company, description=description,
                                      salary_text=salary_text, work_mode=work_mode, prefs=prefs,
                                      require_description=require_description)
    if preference.decision is not Decision.PASS:
        return preference
    return FilterResult(portal.decision, portal.reasons + preference.reasons)


def format_reason(result: FilterResult) -> str:
    prefix = "needs_review: " if result.decision is Decision.REVIEW else ""
    return prefix + "; ".join(result.reasons) if result.reasons else result.decision.value
