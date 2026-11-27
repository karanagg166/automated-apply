"""Education answers from the canonical profile (school, degree, discipline, graduation year).

Never invents: an option is chosen only when it clearly matches the stored value, else "Other"
when the form offers it, else None (the owner is asked once and the answer is cached).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SCHOOL_Q = re.compile(r"^\s*(?:name of (?:your )?|your )?(?:school|university|college|institution|institute)"
                      r"(?:\s+name)?\s*\*?\s*\??\s*$", re.IGNORECASE)
DEGREE_Q = re.compile(r"^\s*(?:highest\s+)?(?:degree|qualification|education level|level of education|degree type)"
                      r"\s*\*?\s*\??\s*$", re.IGNORECASE)
DISCIPLINE_Q = re.compile(r"^\s*(?:discipline|major|field of study|area of study|specialization|specialisation)"
                          r"\s*\*?\s*\??\s*$", re.IGNORECASE)
GRAD_YEAR_Q = re.compile(r"^\s*(?:graduation (?:year|date)|year of graduation|end date year|end year|"
                         r"expected graduation(?: year| date)?)\s*\*?\s*\??\s*$", re.IGNORECASE)
_BACHELOR = re.compile(r"^\s*(?:b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|bca|bachelor)", re.IGNORECASE)
_MASTER = re.compile(r"^\s*(?:m\.?\s?tech|m\.?\s?e\b|m\.?\s?sc|mca|master)", re.IGNORECASE)


@dataclass(frozen=True)
class Education:
    school: str | None = None
    degree: str | None = None
    discipline: str | None = None
    graduation_year: str | None = None


def _text(value: Any) -> str | None:
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    return text or None


def education_from_profile(profile: dict[str, Any]) -> Education | None:
    entries = profile.get("education")
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return None
    latest = max(entries, key=lambda e: str(e.get("graduation_year") or ""))
    return Education(school=_text(latest.get("institution") or latest.get("school")),
                     degree=_text(latest.get("qualification") or latest.get("degree")),
                     discipline=_text(latest.get("field_of_study") or latest.get("major")),
                     graduation_year=_text(latest.get("graduation_year")))


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _unique(options: tuple[str, ...], predicate: Any) -> str | None:
    hits = [o for o in options if predicate(o)]
    return hits[0] if len(hits) == 1 else None


def _other(options: tuple[str, ...]) -> str | None:
    return _unique(options, lambda o: _letters(o) == "other")


def _school(options: tuple[str, ...], school: str) -> str | None:
    if not options:
        return school
    want = _letters(school)
    exact = _unique(options, lambda o: _letters(o) == want)
    if exact:
        return exact
    tokens = [t for t in want.split() if len(t) > 3]
    contains = _unique(options, lambda o: bool(tokens) and all(t in _letters(o) for t in tokens))
    return contains or _other(options)


def _degree(options: tuple[str, ...], degree: str) -> str | None:
    if not options:
        return degree
    exact = _unique(options, lambda o: _letters(o) == _letters(degree))
    if exact:
        return exact
    if _BACHELOR.search(degree):
        level = [o for o in options if re.search(r"bachelor", o, re.IGNORECASE)]
    elif _MASTER.search(degree):
        level = [o for o in options if re.search(r"master", o, re.IGNORECASE)]
    else:
        level = []
    if len(level) == 1:
        return level[0]
    if len(level) > 1:  # "Bachelor's Degree" over "Bachelor of Arts" etc.
        generic = [o for o in level if re.search(r"bachelor'?s(?: degree)?$|master'?s(?: degree)?$", o.strip(),
                                                 re.IGNORECASE)]
        return generic[0] if len(generic) == 1 else None
    return _other(options)


def _discipline(options: tuple[str, ...], discipline: str) -> str | None:
    if not options:
        return discipline
    want = _letters(discipline)
    exact = _unique(options, lambda o: _letters(o) == want)
    if exact:
        return exact
    if "computer science" in want:
        cs = [o for o in options if "computer science" in _letters(o)]
        if len(cs) == 1:
            return cs[0]
        engineering = [o for o in cs if "engineering" in _letters(o)]
        if len(engineering) == 1:
            return engineering[0]
        if cs:
            shortest = min(cs, key=len)
            return shortest if _letters(shortest) == "computer science" else None
    return _other(options)


def education_answer(question: str, options: tuple[str, ...], education: Education | None) -> tuple[bool, str | None]:
    """(handled, answer). handled=False means "not an education question"."""
    label = " ".join(question.replace("*", " ").split())
    if education is None:
        return False, None
    if SCHOOL_Q.search(label) and education.school:
        return True, _school(options, education.school)
    if DEGREE_Q.search(label) and education.degree:
        return True, _degree(options, education.degree)
    if DISCIPLINE_Q.search(label) and education.discipline:
        return True, _discipline(options, education.discipline)
    if GRAD_YEAR_Q.search(label) and education.graduation_year:
        year = education.graduation_year[:4]
        if not options:
            return True, year
        return True, _unique(options, lambda o: _letters(o) == year)
    return False, None


# "How did you hear about us?": the worker finds jobs on the employer's own careers board / ATS or a
# public job board, so the truthful choice is the careers site, then a job board, then "Other".
_HEAR_PREFERENCES = (
    (r"careers? (?:web)?site|company (?:web)?site|company careers|careers page|career site|"
     r"(?:company|corporate) website"),
    (r"job board|online job|job site|job posting|greenhouse|lever|internet|online search|web search|"
     r"google"),
    r"^\s*other\b",
)
_LINK_FIELD = re.compile(r"\b(?:link|url|profile|handle)\b", re.IGNORECASE)


def hear_about_answer(options: tuple[str, ...], question: str = "") -> str | None:
    if _LINK_FIELD.search(question):
        return None  # "How did you hear about us? (LinkedIn profile link)" is a link field, not a source
    if not options:
        return "Company careers page"
    for pattern in _HEAR_PREFERENCES:
        hits = [o for o in options if re.search(pattern, o, re.IGNORECASE)]
        if hits:
            return hits[0]
    return None
