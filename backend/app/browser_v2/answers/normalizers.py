"""Text normalizers, value parsers and exact option matchers."""

from __future__ import annotations

import math
import re
from typing import Any


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", text.lower()).strip()


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()


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
    # Live canary 2026-11-27: Naukri radio values drop apostrophes ("No, I dont have one") while the
    # owner types the label ("No, I don't have one"). Punctuation-insensitive, still exactly one match.
    loose = _punctless(text)
    matches = [option for option in options if loose and _punctless(option) == loose]
    return matches[0] if len(matches) == 1 else None


def _punctless(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", value or "").casefold().split())


def hitl_override(question: str, options: tuple[str, ...], answers: dict[str, str] | None) -> str | None:
    """Owner answer resolved through Telegram/dashboard HITL for this exact question."""
    wanted = normalize(question)
    if not answers or not wanted:
        return None
    for asked, answer in reversed(list(answers.items())):
        if normalize(asked) == wanted:
            return match_option(answer, options) or match_multi(answer, options)
    return None


MULTI_SPLIT = re.compile(r"\s*(?:,|;|\||\band\b)\s*", re.IGNORECASE)


def match_multi(answer: str, options: tuple[str, ...]) -> str | None:
    """Multi-select answer ("Python, Go"): every part must match an option; canonical ", "-joined."""
    parts = [p for p in MULTI_SPLIT.split(answer or "") if p.strip()]
    if len(parts) < 2 or not options:
        return None
    matched = [match_option(part, options) for part in parts]
    if not all(matched):
        return None
    return ", ".join(dict.fromkeys(m for m in matched if m))


def choose_yes_no(options: tuple[str, ...], yes: bool) -> str | None:
    pattern = re.compile(r"^(?:yes|y)\b" if yes else r"^(?:no|n)\b", re.IGNORECASE)
    matches = [o for o in options if pattern.match(o.strip())]
    return matches[0] if len(matches) == 1 else (None if options else ("Yes" if yes else "No"))


def lakhs(value: str | None) -> float | None:
    """Stored CTC (LPA) as a number; legacy text like "8 LPA" is accepted."""
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|l)?\s*", value, re.IGNORECASE)
    return float(match.group(1)) if match else None
