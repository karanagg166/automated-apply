"""Deterministic answer helpers (notice, CTC, thresholds, authorization, links)."""

from __future__ import annotations

import re

from backend.app.browser_v2.answers.classifier import (
    FOREIGN_PAY,
    GENERIC_FIELDS,
    GITHUB_Q,
    LAKH_UNIT,
    LINK_CONTEXT,
    LINKEDIN_Q,
    MONTHLY,
    PORTFOLIO_Q,
    RUPEE_UNIT,
    SPONSORSHIP_Q,
    THRESHOLD_SKILL,
    WORK_AUTH_Q,
    YEARS_THRESHOLD,
    YES_NO_QUESTION,
)
from backend.app.browser_v2.answers.facts import CandidateFacts
from backend.app.browser_v2.answers.geography import countries_mentioned
from backend.app.browser_v2.answers.normalizers import (
    _letters,
    _years,
    choose_option,
    choose_yes_no,
    lakhs,
    normalize,
)


def choose_notice(options: tuple[str, ...], days: int) -> str | None:
    if not options:
        return str(days)
    best: tuple[int, str] | None = None
    for option in options:
        text = option.lower()
        if re.search(r"immediate|serving|\b0 days?\b", text):
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


def ctc_answer(question: str, options: tuple[str, ...], stored: str | None) -> str | None:
    """CTC in the unit the question asks for. Monthly / hourly / non-INR figures need a human."""
    if stored is None or MONTHLY.search(question) or FOREIGN_PAY.search(question) \
            or any(FOREIGN_PAY.search(o) for o in options):
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


def choose_text_option(options: tuple[str, ...], answer: str) -> str | None:
    """Stored free-text fact -> exact option, else the single option containing it (word-bounded)."""
    exact = choose_option(options, answer)
    if exact is not None or not options:
        return exact
    wanted = _letters(answer)
    hits = [o for o in options if wanted and (f" {wanted} " in f" {_letters(o)} "
                                              or f" {_letters(o)} " in f" {wanted} ")]
    return hits[0] if len(hits) == 1 else None


def _threshold_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    """(handled, answer) for "at least N years of experience [in X]?" yes/no questions."""
    match = YEARS_THRESHOLD.search(question)
    if not match or (options and not _yes_no_only(options)) or not YES_NO_QUESTION.search(question):
        return False, None
    rest = match.group("rest")
    skill = THRESHOLD_SKILL.match(rest) if rest.strip(" ?.") else None
    if rest.strip(" ?.") and skill is None:
        return True, None  # "... experience as a team lead?" - not a stored fact
    if skill is not None and normalize(skill.group("skill")) not in GENERIC_FIELDS:
        years = facts.skill_years.get(normalize(skill.group("skill")))
    else:
        years = facts.experience_years
    if years is None:
        return True, None  # never claim N years we cannot verify
    needed = float(match.group("n"))
    strict = (match.group("op") or "").lower() in ("more than", "over")
    return True, choose_yes_no(options, years > needed if strict else years >= needed)


def _authorization_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    """Work authorization / sponsorship from preferences.work_authorizations (per country) or the
    free-text preferences.work_authorization status. Unknown country -> human."""
    sponsorship = bool(SPONSORSHIP_Q.search(question))
    if not sponsorship and not WORK_AUTH_Q.search(question):
        return False, None
    yes_no = not options or _yes_no_only(options)
    mentioned = countries_mentioned(question)
    if yes_no and len(mentioned) == 1:
        code = next(iter(mentioned))
        row = next((r for r in facts.work_authorizations if r.country_code == code), None)
        if row is None:
            return True, None
        value = row.requires_sponsorship if sponsorship else row.authorized
        return True, None if value is None else choose_yes_no(options, value)
    if facts.work_authorization and not sponsorship and not mentioned and (not options or not yes_no) \
            and not YES_NO_QUESTION.search(question):
        return True, choose_text_option(options, facts.work_authorization)
    return True, None


def _link_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    if options or LINK_CONTEXT.search(question) or YES_NO_QUESTION.search(question):
        return False, None
    for pattern, key in ((LINKEDIN_Q, "linkedin_url"), (GITHUB_Q, "github_url"), (PORTFOLIO_Q, "portfolio_url")):
        if pattern.search(question):
            return True, facts.identity.get(key)
    return False, None


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
