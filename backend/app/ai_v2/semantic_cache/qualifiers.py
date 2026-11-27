"""Qualifier extraction: the entity-mismatch guard for semantic cache hits."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.ai_v2.semantic_cache.models import normalize_question
from backend.app.browser_v2.tech_terms import phrase_terms, tech_terms

# --- qualifier extraction (entity-mismatch guard) -------------------------------------
_CITY_ALIASES = {
    "bangalore": "bengaluru", "bombay": "mumbai", "gurugram": "gurgaon", "madras": "chennai",
    "calcutta": "kolkata", "new delhi": "delhi", "trivandrum": "thiruvananthapuram",
    "poona": "pune", "noida extension": "noida", "navi mumbai": "navi mumbai", "ncr": "delhi ncr",
    "delhi ncr": "delhi ncr", "sf": "san francisco", "nyc": "new york",
}
_CITIES = frozenset({
    "bengaluru", "mumbai", "delhi", "delhi ncr", "gurgaon", "noida", "hyderabad", "chennai", "kolkata",
    "pune", "ahmedabad", "jaipur", "chandigarh", "kochi", "thiruvananthapuram", "indore", "bhopal",
    "lucknow", "nagpur", "coimbatore", "mysuru", "mysore", "vadodara", "surat", "visakhapatnam",
    "bhubaneswar", "goa", "mohali", "dehradun", "navi mumbai", "thane", "faridabad", "ghaziabad",
    "london", "berlin", "singapore", "dubai", "new york", "san francisco", "seattle", "toronto",
    "amsterdam", "dublin", "sydney", "tokyo",
})
_TEMPORAL = {
    "current": re.compile(r"\b(?:current(?:ly)?|present|existing|now|today)\b"),
    "expected": re.compile(r"\b(?:expected|expecting|expectation|desired|target|asking)\b"),
    "previous": re.compile(r"\b(?:previous|last|prior|former)\b"),
}
_UNITS = {
    "lakh": re.compile(r"\b(?:lakhs?|lacs?|lpa|l p a)\b"),
    "inr": re.compile(r"\b(?:inr|rupees?|rs)\b|₹"),
    "usd": re.compile(r"\b(?:usd|dollars?)\b|\$"),
    "monthly": re.compile(r"\b(?:per month|monthly|a month|pm)\b"),
    "annual": re.compile(r"\b(?:per annum|annual(?:ly)?|yearly|per year|pa)\b"),
    "hourly": re.compile(r"\b(?:per hour|hourly)\b"),
    "days": re.compile(r"\bdays?\b"),
    "weeks": re.compile(r"\bweeks?\b"),
    "months": re.compile(r"\bmonths?\b"),
}
_WORK_MODE = {
    "remote": re.compile(r"\b(?:remote(?:ly)?|work from home|wfh)\b"),
    "hybrid": re.compile(r"\bhybrid\b"),
    "onsite": re.compile(r"\b(?:on ?site|in office|office|work from office|wfo)\b"),
}
_EMPLOYMENT = {
    "full_time": re.compile(r"\bfull ?time\b"),
    "part_time": re.compile(r"\bpart ?time\b"),
    "contract": re.compile(r"\b(?:contract(?:ual)?|freelance|c2h)\b"),
    "internship": re.compile(r"\b(?:intern(?:ship)?)\b"),
    "night_shift": re.compile(r"\bnight shifts?\b"),
}
_NEGATION = re.compile(r"\b(?:not|never|no|without|n t|cannot|can t|don t|won t|unable|no longer|except)\b")
# Regions a work-authorization / relocation question can name besides a single country.
_REGIONS = {
    "eu": re.compile(r"\b(?:eu|european union|europe|eea|schengen)\b"),
    "north_america": re.compile(r"\bnorth america\b"),
    "apac": re.compile(r"\b(?:apac|asia pacific)\b"),
    "emea": re.compile(r"\bemea\b"),
    "latam": re.compile(r"\b(?:latam|latin america)\b"),
}
# Opposite-intent pairs: two questions that share almost every word but ask opposite things.
_POLARITY = {
    "needs_sponsorship": re.compile(r"\b(?:require|need|needs|requiring|will you need|will you require)\b.*\bsponsor"),
    "no_sponsorship": re.compile(r"\bwithout\b.*\bsponsor|\bsponsor\w*\b.*\bnot (?:be )?(?:required|needed)\b"),
    "future_move": re.compile(r"\b(?:relocat\w*|willing to (?:move|shift)|open to (?:moving|relocat\w*))\b"),
    "current_residence": re.compile(r"\b(?:currently|presently|now)\s+(?:located|based|living|residing)\b|"
                                    r"\bdo you (?:live|reside)\b"),
    "ever": re.compile(r"\b(?:have you ever|ever been|ever had|ever worked|previously)\b"),
    "currently_are": re.compile(r"\bare you currently\b|\bdo you currently\b"),
    "adult": re.compile(r"\b(?:18|eighteen) (?:years )?(?:of age )?(?:or|and) (?:older|above|over)\b|"
                        r"\b(?:over|above|at least) (?:the age of )?(?:18|eighteen)\b"),
    "minor": re.compile(r"\b(?:under|below|younger than|less than) (?:the age of )?(?:18|eighteen)\b"),
    "minimum": re.compile(r"\b(?:minimum|least|lowest)\b"),
    "maximum": re.compile(r"\b(?:maximum|most|highest)\b"),
}
POLARITY_FIELDS = ("negation", "polarity", "temporal")
ENTITY_FIELDS = ("tech", "city", "country", "unit", "number", "work_mode", "employment")


@dataclass(frozen=True)
class Qualifiers:
    tech: frozenset[str] = frozenset()
    temporal: frozenset[str] = frozenset()
    city: frozenset[str] = frozenset()
    unit: frozenset[str] = frozenset()
    number: frozenset[str] = frozenset()
    negation: bool = False
    work_mode: frozenset[str] = frozenset()
    employment: frozenset[str] = frozenset()
    country: frozenset[str] = frozenset()  # ISO codes + regions (eu, apac, ...)
    polarity: frozenset[str] = frozenset()  # opposite-intent tags (needs_sponsorship vs no_sponsorship ...)

    def differences(self, other: Qualifiers) -> list[str]:
        names = ("tech", "temporal", "city", "unit", "number", "negation", "work_mode", "employment",
                 "country", "polarity")
        return [name for name in names if getattr(self, name) != getattr(other, name)]

    def entities(self) -> dict[str, list[str]]:
        """JSON-friendly snapshot stored with a cache entry (non-empty entity sets only)."""
        out = {name: sorted(getattr(self, name)) for name in ("tech", "city", "country", "work_mode", "employment")}
        return {k: v for k, v in out.items() if v}


_NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
                 "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40", "forty five": "45",
                 "sixty": "60", "ninety": "90"}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b")


def _countries(question: str, text: str) -> frozenset[str]:
    from backend.app.browser_v2.answers.geography import countries_mentioned

    found = set(countries_mentioned(question or ""))
    found.update(name for name, pattern in _REGIONS.items() if pattern.search(text))
    return frozenset(found)


def extract_qualifiers(question: str) -> Qualifiers:
    text = _NUMBER_WORD.sub(lambda m: _NUMBER_WORDS[m.group(1)], normalize_question(question))
    numbers = frozenset(re.findall(r"(?<![a-z])\d+(?:\.\d+)?", text))
    return Qualifiers(
        tech=tech_terms(text),
        temporal=frozenset(k for k, p in _TEMPORAL.items() if p.search(text)),
        city=phrase_terms(text, _CITIES, _CITY_ALIASES),
        unit=frozenset(k for k, p in _UNITS.items() if p.search(text)),
        number=numbers,
        negation=bool(_NEGATION.search(text)),
        work_mode=frozenset(k for k, p in _WORK_MODE.items() if p.search(text)),
        employment=frozenset(k for k, p in _EMPLOYMENT.items() if p.search(text)),
        country=_countries(question, text),
        polarity=frozenset(k for k, p in _POLARITY.items() if p.search(text)),
    )


def qualifiers_conflict(query: str | Qualifiers, cached: str | Qualifiers) -> list[str]:
    """Qualifier categories that differ (empty list = compatible)."""
    left = query if isinstance(query, Qualifiers) else extract_qualifiers(query)
    right = cached if isinstance(cached, Qualifiers) else extract_qualifiers(cached)
    return left.differences(right)
