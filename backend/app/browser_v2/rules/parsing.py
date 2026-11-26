"""Pure parsers for portal card/JD text: applicants, posting age, experience, salary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime


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


_EXPERIENCE_RANGE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:-|–|to)\s*(\d{1,2}(?:\.\d)?)\s*(?:\+\s*)?(?:yrs?|years?)\b",
                               re.IGNORECASE)
_EXPERIENCE_MIN = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:yrs?|years?)\b", re.IGNORECASE)


def parse_experience_range(text: str | None) -> tuple[float | None, float | None]:
    """"0 - 5 years" -> (0, 5); "4-5 Yrs" -> (4, 5); "3+ years" -> (3, None); "Fresher" -> (0, 1)."""
    if not text:
        return None, None
    if re.search(r"\bfresher", text, re.IGNORECASE):
        return 0.0, 1.0
    match = _EXPERIENCE_RANGE.search(text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return min(low, high), max(low, high)
    match = _EXPERIENCE_MIN.search(text)
    return (float(match.group(1)), None) if match else (None, None)


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
