"""Deterministic keys: canonical question text, option/scope hashes, the exact-lookup key and the
candidate profile version hash used to invalidate factual cache entries."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from backend.app.ai_v2.semantic_cache.models import normalize_question

if TYPE_CHECKING:
    from backend.app.browser_v2.answers import CandidateFacts

# "Q1.", "1)", "2 -", "(a)", "*", "(required)", "required" markers around a form label.
_PREFIX = re.compile(r"^\s*(?:q(?:uestion)?\s*\d+\s*[.):-]?|\(?\d{1,2}\s*[.):-]|\(?[a-h]\)|[-*•]+)\s*", re.IGNORECASE)
_REQUIRED = re.compile(r"(?:\s*(?:[*✱✳＊]|\((?:required|mandatory)\)|\brequired\b))+\s*$", re.IGNORECASE)
COMPANY_TOKEN = "company"


def canonical_question(text: str, company: str | None = None) -> str:
    """normalize_question() after stripping numbering prefixes and required markers. The current
    job's company name is replaced by a neutral token, so "Why join Stripe?" and "Why join Razorpay?"
    share one canonical text (and are kept apart by the company scope instead)."""
    value = _REQUIRED.sub("", _PREFIX.sub("", text or "", count=1))
    normalized = normalize_question(value)
    name = normalize_question(company or "")
    if name and len(name) >= 2:
        normalized = re.sub(rf"(?<![a-z0-9+#]){re.escape(name)}(?![a-z0-9+#])", COMPANY_TOKEN, normalized)
    return normalized


def company_slug(company: str | None) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")
    for suffix in ("-private-limited", "-pvt-ltd", "-limited", "-ltd", "-inc", "-llc", "-technologies", "-labs"):
        if slug.endswith(suffix) and len(slug) > len(suffix):
            slug = slug[: -len(suffix)]
    return slug[:80] or None


def storage_key(canonical: str, scope_slug: str | None) -> str:
    """Value of the (kind, normalized_question) unique key. Company-scoped rows carry their slug, so
    one question can hold one answer per company without changing the 004 constraint. Global rows
    keep the plain canonical text, so every pre-006 row still exact-matches."""
    return f"{canonical} @{scope_slug}" if scope_slug else canonical


def options_hash(options: Iterable[str]) -> str | None:
    cleaned = sorted({normalize_question(o) for o in options if normalize_question(o)})
    return hashlib.sha256("|".join(cleaned).encode()).hexdigest()[:16] if cleaned else None


def cache_key(*, intent: str, field_type: str, canonical: str, options: Iterable[str] = (),
              scope_slug: str | None = None, profile_hash: str | None = None) -> str:
    """sha256(intent | field_type | canonical question | sorted options hash | scope | profile hash)."""
    parts = (intent, field_type, canonical, options_hash(options) or "", scope_slug or "global", profile_hash or "")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _round(value: Any) -> Any:
    return round(value, 2) if isinstance(value, float) else value


def profile_version_hash(facts: CandidateFacts | None) -> str | None:
    """SHA-256 over the factual profile fields a cached factual answer depends on (CTC, notice
    period, years of experience, location, relocation, authorization, skills, education, resume)."""
    if facts is None:
        return None
    education = facts.education
    payload = {
        "experience_years": _round(facts.experience_years),
        "skills": sorted(normalize_question(s) for s in facts.skills),
        "skill_years": {k: _round(v) for k, v in sorted(facts.skill_years.items())},
        "notice_period_days": facts.notice_period_days,
        "current_ctc": facts.current_ctc, "expected_ctc": facts.expected_ctc,
        "current_location": facts.current_location, "city": facts.city, "country_code": facts.country_code,
        "willing_to_relocate": facts.willing_to_relocate,
        "relocation_locations": sorted(facts.relocation_locations),
        "current_company": facts.current_company, "current_title": facts.current_title,
        "work_authorization": facts.work_authorization,
        "work_authorizations": sorted((w.country_code, w.authorized, w.requires_sponsorship)
                                      for w in facts.work_authorizations),
        "education": repr(education) if education is not None else None,
        "resume_files": sorted(str(k) for k in (facts.resume_files or {})),
        "english": facts.english_proficiency,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def profile_hash_from_profile(profile: dict[str, Any] | None) -> str | None:
    if not isinstance(profile, dict) or not profile:
        return None
    from backend.app.browser_v2.answers import CandidateFacts

    return profile_version_hash(CandidateFacts.from_profile(profile))
