"""Pure per-field normalisation and diffing for the portal profile sync.

Rules:
- text fields compare after whitespace collapsing (case kept: a recruiter sees the casing);
- skills compare case-insensitively and are ADD-ONLY: a portal skill missing from the profile
  is reported as a removal but never removed;
- CTC compares as INR lakhs per annum (LPA) numbers, notice period as days, locations as a
  case-insensitive set;
- a non-empty portal value is never overwritten with an empty/None source value
  (``skipped_empty_source``); an empty source is never written at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from backend.app.browser_v2.profile_sync.models import (
    FIELDS,
    FieldDiff,
    FieldStatus,
    FieldValue,
)

TEXT_FIELDS = frozenset({"resume_headline", "profile_summary", "current_location"})
LIST_FIELDS = frozenset({"key_skills", "preferred_locations"})
CTC_FIELDS = frozenset({"current_ctc", "expected_ctc"})
CTC_TOLERANCE = 0.01
_NUMBER = r"(\d+(?:\.\d+)?)"
_CRORE = re.compile(_NUMBER + r"\s*(?:cr|crore|crores)\b")
_LAKH = re.compile(_NUMBER + r"\s*(?:lpa|l|lakh|lakhs|lac|lacs)\b")
_THOUSAND = re.compile(_NUMBER + r"\s*(?:k|thousand|thousands)\b")
_PLAIN = re.compile(r"^\s*" + _NUMBER + r"\s*$")
_DAYS = re.compile(r"(\d+)\s*(day|days|week|weeks|month|months)\b")
_IMMEDIATE = re.compile(r"\b(?:immediate|immediately|serving notice|currently serving)\b")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def clean_list(value: Any) -> list[str]:
    """List (or comma/newline separated string) -> stripped, de-duplicated (case-insensitive)."""
    if value is None:
        return []
    items: Iterable[Any] = re.split(r"[,\n;]", value) if isinstance(value, str) else value
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = clean_text(item)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def parse_lpa(value: Any) -> float | None:
    """CTC as LPA: 12.5 -> 12.5, 1250000 -> 12.5, "12.5 LPA" / "12 Lacs 50 Thousand" / "₹ 12,50,000"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number / 100_000 if number > 1000 else number, 2) if number >= 0 else None
    text = str(value).lower().replace(",", "").replace("₹", " ").replace("inr", " ").replace("rs.", " ")
    if crore := _CRORE.search(text):
        return round(float(crore.group(1)) * 100, 2)
    lakh = _LAKH.search(text)
    thousand = _THOUSAND.search(text)
    if lakh or thousand:
        total = float(lakh.group(1)) if lakh else 0.0
        if thousand:
            total += float(thousand.group(1)) / 100
        return round(total, 2)
    if plain := _PLAIN.match(text):
        return parse_lpa(float(plain.group(1)))
    return None


def parse_notice_days(value: Any) -> int | None:
    """Notice period in days: 30 -> 30, "1 Month" -> 30, "15 Days or less" -> 15, "Immediate" -> 0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    text = str(value).lower()
    if match := _DAYS.search(text):
        number, unit = int(match.group(1)), match.group(2)
        return number * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)
    if _IMMEDIATE.search(text):
        return 0
    if plain := _PLAIN.match(text):
        return int(float(plain.group(1)))
    return None


def resume_sha(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("sha256")
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) else None


def normalize(field: str, value: Any) -> Any:
    """Comparable form of a value; None/empty means "no value"."""
    if field in TEXT_FIELDS:
        return clean_text(value)
    if field in LIST_FIELDS:
        return frozenset(item.casefold() for item in clean_list(value)) or None
    if field in CTC_FIELDS:
        return parse_lpa(value)
    if field == "notice_period":
        return parse_notice_days(value)
    if field == "resume_pdf":
        return resume_sha(value)
    return clean_text(value)


def is_empty(field: str, value: Any) -> bool:
    return normalize(field, value) is None


def values_match(field: str, expected: Any, observed: Any) -> bool:
    """Verify-after-write: skills only need every expected skill present (add-only)."""
    want, got = normalize(field, expected), normalize(field, observed)
    if want is None or got is None:
        return False
    if field == "key_skills":
        return bool(want <= got)
    if field in CTC_FIELDS:
        return abs(float(want) - float(got)) < CTC_TOLERANCE
    return bool(want == got)


def _skills_diff(source: Any, portal: Any) -> FieldDiff:
    wanted, current = clean_list(source), clean_list(portal)
    have = {item.casefold() for item in current}
    keep = {item.casefold() for item in wanted}
    additions = tuple(item for item in wanted if item.casefold() not in have)
    removals = tuple(item for item in current if item.casefold() not in keep)
    if not additions:
        return FieldDiff("key_skills", FieldStatus.UNCHANGED, current, current, removals=removals,
                         reason="removals_not_applied" if removals else None)
    return FieldDiff("key_skills", FieldStatus.WOULD_UPDATE, current, [*current, *additions],
                     additions=additions, removals=removals,
                     reason="removals_not_applied" if removals else None)


def diff_field(field: str, source: Any, portal: FieldValue | None) -> FieldDiff:
    if portal is None:
        return FieldDiff(field, FieldStatus.ERROR, reason="portal_value_unreadable")
    if portal.status is not None:
        return FieldDiff(field, portal.status, reason=portal.reason)
    if is_empty(field, source):
        return FieldDiff(field, FieldStatus.SKIPPED_EMPTY_SOURCE, portal.value,
                         reason="portal_value_kept" if not is_empty(field, portal.value) else None)
    if field == "key_skills":
        return _skills_diff(source, portal.value)
    if values_match(field, source, portal.value):
        return FieldDiff(field, FieldStatus.UNCHANGED, portal.value, source)
    return FieldDiff(field, FieldStatus.WOULD_UPDATE, portal.value, source)


def compute_diff(canonical: Mapping[str, Any], portal: Mapping[str, FieldValue],
                 supported: Iterable[str], fields: Iterable[str] = FIELDS) -> list[FieldDiff]:
    """One FieldDiff per canonical field; fields the portal does not have are skipped_unsupported."""
    supported_set = frozenset(supported)
    out: list[FieldDiff] = []
    for name in fields:
        if name not in supported_set:
            out.append(FieldDiff(name, FieldStatus.SKIPPED_UNSUPPORTED))
        else:
            out.append(diff_field(name, canonical.get(name), portal.get(name)))
    return out
