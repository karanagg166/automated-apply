"""Deterministic screening answers from verified profile facts only.

Anything not backed by a stored fact returns None so the caller raises a
WAITING_FOR_USER (HITL) request instead of guessing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.app.browser_v2.tech_terms import is_known_tech

# Ported from extension/naukri-chatbot.js + backend/app/knowledge/missing_input.py.
BLOCKED = re.compile(r"\b(?:email|e-mail|login|password|otp|consent|terms and conditions)\b", re.IGNORECASE)
SENSITIVE = re.compile(
    r"password|passcode|verification code|one.time (?:code|password)|social security|"
    r"government (?:id|identifier)|aadhaar|aadhar|pan (?:card|number)|passport|bank account|"
    r"credit card|\bcvv\b|\botp\b|sexual orientation|gender identity|ethnicity|disabilit|"
    r"veteran|religio|consent|legal declaration|terms and conditions", re.IGNORECASE)
TOTAL_EXPERIENCE = re.compile(
    r"\b(?:total|overall)\s+(?:years of\s+)?(?:work\s+|professional\s+)?experience\b|"
    r"\byears of (?:professional |work |total )?experience\b(?!\s+(?:in|with|using|on)\b)|"
    r"\bhow many years of experience do you have\b(?!\s+(?:in|with|using|on)\b)", re.IGNORECASE)
SKILL_EXPERIENCE = re.compile(
    r"\b(?:experience|exp)\b.*?\b(?:in|with|using|on)\s+(?P<skill>[A-Za-z0-9.+#/ -]{1,40}?)\s*\??$",
    re.IGNORECASE)
SKILL_YES_NO = re.compile(
    r"\b(?:do you have|have you (?:worked|used)|are you (?:familiar|proficient|comfortable))\b"
    r".*?\b(?:with|in|on|using)?\s*(?P<skill>[A-Za-z0-9.+#/ -]{1,40}?)\s*(?:experience)?\s*\??$",
    re.IGNORECASE)
NOTICE = re.compile(r"\bnotice period\b|\bhow soon can you join\b|\bjoin(?:ing)? (?:date|time)\b", re.IGNORECASE)
CURRENT_CTC = re.compile(r"\bcurrent\s+(?:ctc|salary|compensation|package)\b", re.IGNORECASE)
EXPECTED_CTC = re.compile(r"\bexpected\s+(?:ctc|salary|compensation|package)\b", re.IGNORECASE)
CURRENT_LOCATION = re.compile(r"\bcurrent(?:ly)?\s+(?:location|based|city|residing)\b|\bwhere are you (?:currently )?(?:located|based)\b", re.IGNORECASE)
GENERIC_FIELDS = frozenset({"total", "overall", "years", "year", "total years", "it", "the it industry", "it industry", "industry",
                            "software", "software development", "this field", "the field",
                            "this role", "a similar role", "similar role"})
RELOCATE = re.compile(r"\b(?:relocat\w*|willing to (?:move|shift))\b", re.IGNORECASE)
RELOCATE_TARGET = re.compile(r"\b(?:relocat\w*|move|shift)\s+to\s+(?P<city>[A-Za-z .-]{2,40}?)\s*\??$", re.IGNORECASE)
LOCATED_IN = re.compile(
    r"\b(?:are you|do you)\s+(?:currently\s+)?(?:located|based|living|residing|stay(?:ing)?)\s+(?:in|at|near)\s+"
    r"(?P<city>[A-Za-z .-]{2,40}?)\s*\??$", re.IGNORECASE)
IMMEDIATE_JOINER = re.compile(r"\bimmediate(?:ly)?\s+(?:joiner|join|available|start)\b|\bjoin immediately\b", re.IGNORECASE)
JOIN_WITHIN = re.compile(r"\b(?:join|start)\b.*?\bwithin\s+(?P<n>\d+)\s*(?P<unit>days?|weeks?|months?)\b", re.IGNORECASE)
LAKH_UNIT = re.compile(r"\b(?:lakhs?|lacs?|lpa|l\.p\.a)\b", re.IGNORECASE)
RUPEE_UNIT = re.compile(r"\b(?:in rupees|in inr|inr|rupees)\b|₹", re.IGNORECASE)
MONTHLY = re.compile(r"\b(?:per month|monthly|in hand per month|/\s*month)\b", re.IGNORECASE)


class ResolvedLike(Protocol):
    @property
    def answer(self) -> str | None: ...

    @property
    def source(self) -> str: ...

    @property
    def reason(self) -> str: ...


class ScreeningResolver(Protocol):
    """Tiered resolver (ai_v2.screening.ScreeningAnswerer); Tier 0 is always resolve_answer()."""

    async def resolve(self, question: str, options: tuple[str, ...], facts: CandidateFacts,
                      context: dict[str, Any] | None = None) -> ResolvedLike: ...


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", text.lower()).strip()


IDENTITY_KEYS = ("full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url",
                 "personal_website")


def identity_fields(profile: dict[str, Any]) -> dict[str, str]:
    """Stored identity values only (first/last name split from full_name); never invented."""
    values = {key: profile[key].strip() for key in IDENTITY_KEYS
              if isinstance(profile.get(key), str) and profile[key].strip()}
    prefs = profile.get("preferences") or {}
    location = prefs.get("current_location") if isinstance(prefs, dict) else None
    if isinstance(location, str) and location.strip():
        values["current_location"] = location.strip()
    name = values.get("full_name", "")
    if name:
        first, _, last = name.partition(" ")
        values["first_name"] = first
        if last.strip():
            values["last_name"] = last.strip()
    if "portfolio_url" not in values and "personal_website" in values:
        values["portfolio_url"] = values["personal_website"]
    return values


@dataclass
class CandidateFacts:
    experience_years: float | None = None
    skills: tuple[str, ...] = ()
    skill_years: dict[str, float] = field(default_factory=dict)
    notice_period_days: int | None = None
    current_ctc: str | None = None  # LPA ("12" or legacy free text like "8 LPA")
    expected_ctc: str | None = None
    current_location: str | None = None
    willing_to_relocate: bool | None = None
    saved_answers: dict[str, str] = field(default_factory=dict)
    # Phase 6A: identity fields typed deterministically into hosted ATS forms (never sent
    # to an LLM) and the owner's local resume PDFs (preferences.resume_files).
    identity: dict[str, str] = field(default_factory=dict)
    resume_files: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: dict[str, Any],
                     reviewed_answers: list[tuple[str, str]] | None = None) -> CandidateFacts:
        prefs = profile.get("preferences") or {}
        skills = []
        for item in profile.get("verified_skills") or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                skills.append(name.strip())
        skill_years: dict[str, float] = {}
        for key, value in (prefs.get("skill_years") or {}).items():
            years = _float(value)
            if isinstance(key, str) and normalize(key) and years is not None:
                skill_years[normalize(key)] = years
        total = _float(prefs.get("total_experience_years"))
        # Only explicitly stored facts: never derive expected CTC from min_ctc.
        return cls(
            experience_years=total if total is not None else _float(profile.get("verified_experience_years")),
            skills=tuple(skills),
            skill_years=skill_years,
            notice_period_days=_int(prefs.get("notice_period_days")),
            current_ctc=_text(prefs.get("current_ctc")),
            expected_ctc=_text(prefs.get("expected_ctc")),
            current_location=_text(prefs.get("current_location")),
            willing_to_relocate=prefs.get("willing_to_relocate")
            if isinstance(prefs.get("willing_to_relocate"), bool) else None,
            saved_answers={normalize(q): a for q, a in reviewed_answers or []},
            identity=identity_fields(profile),
            resume_files=dict(prefs.get("resume_files") or {}) if isinstance(prefs.get("resume_files"), dict)
            else {},
        )

    def has_skill(self, skill: str) -> bool:
        wanted = normalize(skill)
        if self.skill_years.get(wanted, 0) > 0:
            return True
        return any(normalize(s) == wanted for s in self.skills)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _years(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def choose_option(options: tuple[str, ...], answer: str) -> str | None:
    """Pick the option that exactly or numerically matches `answer`."""
    if not options:
        return answer
    wanted = normalize(answer)
    for option in options:
        if normalize(option) == wanted:
            return option
    return None


def match_option(answer: str, options: tuple[str, ...]) -> str | None:
    """Owner reply -> exact option: 1-based index, exact text, or case-insensitive match.

    Stricter than choose_option on purpose: a human reply that is not clearly one
    of the options is rejected (the HITL stays OPEN) instead of guessed.
    """
    text = " ".join((answer or "").split())
    if not options:
        return text or None
    if text.isdigit() and 1 <= int(text) <= len(options):
        return options[int(text) - 1]
    folded = text.casefold()
    for option in options:
        if " ".join(option.split()).casefold() == folded:
            return option
    return None


def hitl_override(question: str, options: tuple[str, ...], answers: dict[str, str] | None) -> str | None:
    """Owner answer resolved through Telegram/dashboard HITL for this exact question."""
    wanted = normalize(question)
    if not answers or not wanted:
        return None
    for asked, answer in reversed(list(answers.items())):
        if normalize(asked) == wanted:
            return match_option(answer, options)
    return None


def choose_yes_no(options: tuple[str, ...], yes: bool) -> str | None:
    pattern = re.compile(r"^(?:yes|y)\b" if yes else r"^(?:no|n)\b", re.IGNORECASE)
    matches = [o for o in options if pattern.match(o.strip())]
    return matches[0] if len(matches) == 1 else (None if options else ("Yes" if yes else "No"))


def choose_notice(options: tuple[str, ...], days: int) -> str | None:
    if not options:
        return str(days)
    best: tuple[int, str] | None = None
    for option in options:
        text = option.lower()
        if re.search(r"immediate|serving|0 days?", text):
            limit = 0
        else:
            numbers = [int(n) for n in re.findall(r"\d+", text)]
            if not numbers:
                continue
            factor = 30 if "month" in text else 7 if "week" in text else 1
            limit = max(numbers) * factor
            if re.search(r"more than|above|\+|over", text):
                limit = 10_000
        if limit >= days and (best is None or limit < best[0]):
            best = (limit, option)
    return best[1] if best else None


def lakhs(value: str | None) -> float | None:
    """Stored CTC (LPA) as a number; legacy text like "8 LPA" is accepted."""
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|l)?\s*", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def ctc_answer(question: str, options: tuple[str, ...], stored: str | None) -> str | None:
    """CTC in the unit the question asks for. Monthly figures need a human."""
    if stored is None or MONTHLY.search(question):
        return None
    amount = lakhs(stored)
    if amount is None:
        return choose_option(options, stored)
    if options:
        return _ctc_option(options, amount)
    if LAKH_UNIT.search(question):
        return _years(amount)
    if RUPEE_UNIT.search(question):
        return str(round(amount * 100_000))
    return f"{_years(amount)} LPA"


def _ctc_option(options: tuple[str, ...], amount: float) -> str | None:
    for option in options:
        numbers = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", option)]
        if not numbers:
            continue
        # Rupee-denominated options ("5,00,000 - 10,00,000") are converted to lakhs.
        numbers = [n / 100_000 if n >= 1000 else n for n in numbers]
        low, high = (numbers[0], numbers[-1]) if len(numbers) > 1 else (numbers[0], numbers[0])
        text = option.lower()
        if re.search(r"\+|more than|above|over", text):
            high = float("inf")
        if re.search(r"less than|below|under|upto|up to", text):
            low, high = 0.0, numbers[0]
        if low <= amount <= high:
            return option
    return None


def _same_place(a: str, b: str) -> bool:
    aliases = {"bangalore": "bengaluru", "bombay": "mumbai", "gurugram": "gurgaon", "madras": "chennai",
               "calcutta": "kolkata", "new delhi": "delhi"}
    left, right = normalize(a), normalize(b)
    left, right = aliases.get(left, left), aliases.get(right, right)
    return bool(left) and (left == right or left in right.split() or right in left.split())


def resolve_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> str | None:
    """Return an exact option/text answer, or None when a human must answer."""
    if BLOCKED.search(question) or SENSITIVE.search(question):
        return None
    saved = facts.saved_answers.get(normalize(question))
    if saved:
        return choose_option(options, saved)
    if facts.notice_period_days is not None:
        within = JOIN_WITHIN.search(question)
        if within:
            unit = within.group("unit").lower()
            limit = int(within.group("n")) * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)
            return choose_yes_no(options, facts.notice_period_days <= limit)
        if IMMEDIATE_JOINER.search(question) and (not options or _yes_no_only(options)):
            return choose_yes_no(options, facts.notice_period_days == 0)
        if NOTICE.search(question):
            return choose_notice(options, facts.notice_period_days)
    if CURRENT_CTC.search(question):
        return ctc_answer(question, options, facts.current_ctc)
    if EXPECTED_CTC.search(question):
        return ctc_answer(question, options, facts.expected_ctc)
    located = LOCATED_IN.search(question)
    if located and facts.current_location:
        return choose_yes_no(options, _same_place(located.group("city"), facts.current_location))
    if CURRENT_LOCATION.search(question):
        return choose_option(options, facts.current_location) if facts.current_location else None
    if RELOCATE.search(question):
        target = RELOCATE_TARGET.search(question)
        if target and facts.current_location and _same_place(target.group("city"), facts.current_location):
            return choose_yes_no(options, True)
        if facts.willing_to_relocate is not None:
            return choose_yes_no(options, facts.willing_to_relocate)
        return None
    skill_match = SKILL_EXPERIENCE.search(question) or SKILL_YES_NO.search(question)
    if skill_match and normalize(skill_match.group("skill")) in GENERIC_FIELDS:
        skill_match = None
    if options and _yes_no_only(options) and skill_match:
        skill = skill_match.group("skill")
        if facts.has_skill(skill):
            return choose_yes_no(options, True)
        # "No" only for a recognizable technology; "comfortable with on-call rotations?" is not a
        # skill, so it falls through to the cache / LLM / human instead of a fabricated "No".
        return choose_yes_no(options, False) if is_known_tech(skill) else None
    if skill_match:
        years = facts.skill_years.get(normalize(skill_match.group("skill")))
        if years is None:
            return None
        return _numeric_option(options, years) if options else _years(years)
    if TOTAL_EXPERIENCE.search(question) and facts.experience_years is not None:
        return (_numeric_option(options, facts.experience_years) if options
                else _years(facts.experience_years))
    return None


def _yes_no_only(options: tuple[str, ...]) -> bool:
    return all(re.match(r"^(?:yes|no|y|n)\b", o.strip(), re.IGNORECASE) for o in options)


def _numeric_option(options: tuple[str, ...], years: float) -> str | None:
    for option in options:
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", option)]
        if not numbers:
            continue
        low, high = (numbers[0], numbers[-1]) if len(numbers) > 1 else (numbers[0], numbers[0])
        if re.search(r"\+|more than|above", option.lower()):
            high = float("inf")
        if re.search(r"less than|below|under", option.lower()):
            low, high = 0.0, numbers[0]
        if low <= years <= high:
            return option
    return None
