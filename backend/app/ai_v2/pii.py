"""Deterministic PII scrubbing and the safe candidate context sent to external LLMs.

Free LLM tiers may log prompts. `scrub_pii` is applied by the router to every
prompt before dispatch, so callers cannot bypass it; `build_safe_llm_profile`
keeps only professional, non-identifying context.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = {
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "pan": "[REDACTED_PAN]",
    "aadhaar": "[REDACTED_AADHAAR]",
    "secret": "[REDACTED_SECRET]",
    "url": "[REDACTED_URL]",
    "private": "[REDACTED]",
}

# Credentials first so a token embedded in a URL or header never survives partially.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|rk|gsk|ghp|gho|ghu|ghs|github_pat|xox[abprs]|AIza|hf)[-_][A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"(?i)\b(?:api[_-]?key|apikey|secret|password|passwd|pwd|access[_-]?token|refresh[_-]?token|"
               r"session[_-]?id|sessionid|cookie|set-cookie|authorization|otp)\s*[:=]\s*[^\s,;]{4,}"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),  # long hex secrets / session ids
)
_CREDENTIAL_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
# +91 / 0-prefixed Indian mobiles, bare 10-digit mobiles and generic international numbers.
_PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"(?:\+|00)\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){2,4}"
    r"|(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}"
    r"|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"
    r")(?!\w)")
_URL_QUERY_SECRET = re.compile(r"([?&](?:token|key|apikey|api_key|sig|signature|auth|session|code)=)[^&\s]+",
                               re.IGNORECASE)

# Domains that are never personal (placeholders, documentation, generic role inboxes).
SAFE_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net", "example.invalid"})


def _replace_email(match: re.Match[str], allowed: frozenset[str]) -> str:
    domain = match.group(0).rsplit("@", 1)[-1].lower()
    return match.group(0) if domain in allowed else REDACTED["email"]


def _secret_variants(value: str) -> list[str]:
    value = value.strip()
    variants = [value]
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:  # phone numbers: also strip the bare digits / last 10 digits
        variants.extend({digits, digits[-10:]})
    if value.startswith(("http://", "https://")):
        variants.append(re.sub(r"^https?://(?:www\.)?", "", value).rstrip("/"))
    return [v for v in variants if len(v) >= 3]


def scrub_pii(text: str, extra_secrets: Iterable[str] = (), *,
              allowed_email_domains: Iterable[str] = ()) -> str:
    """Redact phones, personal emails, PAN/Aadhaar, tokens/keys/cookies, credential URLs and
    every explicit `extra_secrets` value (owner phone, email, name, address, profile links)."""
    if not text:
        return text
    allowed = SAFE_EMAIL_DOMAINS | {d.lower().lstrip("@") for d in allowed_email_domains}
    result = text
    secrets = sorted({variant for secret in extra_secrets if isinstance(secret, str) and secret.strip()
                      for variant in _secret_variants(secret)}, key=len, reverse=True)
    for secret in secrets:
        result = re.sub(rf"(?<![\w@]){re.escape(secret)}(?![\w@])", REDACTED["private"], result,
                        flags=re.IGNORECASE)
    result = _CREDENTIAL_URL.sub(REDACTED["url"], result)
    result = _URL_QUERY_SECRET.sub(lambda m: m.group(1) + REDACTED["secret"], result)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED["secret"], result)
    result = _EMAIL.sub(lambda m: _replace_email(m, frozenset(allowed)), result)
    result = _PAN.sub(REDACTED["pan"], result)
    result = _AADHAAR.sub(REDACTED["aadhaar"], result)
    result = _PHONE.sub(REDACTED["phone"], result)
    return result


def profile_secrets(profile: Mapping[str, Any]) -> list[str]:
    """Exact owner identifiers that must never reach an external LLM."""
    secrets: list[str] = []
    for key in ("full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url",
                "personal_website", "address", "street_address"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            secrets.append(value.strip())
    name = profile.get("full_name")
    if isinstance(name, str):
        secrets.extend(part for part in re.split(r"\s+", name.strip()) if len(part) >= 3)
    prefs = profile.get("preferences") or {}
    for key in ("address", "street_address", "current_ctc", "expected_ctc"):
        value = prefs.get(key) if isinstance(prefs, Mapping) else None
        if isinstance(value, str) and len(value.strip()) >= 3:
            secrets.append(value.strip())
    return secrets


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strings(values: Any, limit: int = 30) -> list[str]:
    out: list[str] = []
    for item in values or []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip()[:80])
    return out[:limit]


def _city(value: Any) -> str | None:
    """City-level location only: the first comma-separated part, digits (PIN codes) removed."""
    if not isinstance(value, str) or not value.strip():
        return None
    city = re.sub(r"\d+", "", value.split(",")[0]).strip(" -")
    return city[:60] or None


def build_safe_llm_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Professional, non-identifying context only: never name, phone, email, links,
    street address, CTC figures, credentials or cookies."""
    prefs = profile.get("preferences") or {}
    if not isinstance(prefs, Mapping):
        prefs = {}
    skill_years = {str(k)[:60]: years for k, v in (prefs.get("skill_years") or {}).items()
                   if (years := _number(v)) is not None}
    total = _number(prefs.get("total_experience_years"))
    if total is None:
        total = _number(profile.get("verified_experience_years"))
    projects = []
    for project in profile.get("projects") or []:
        if isinstance(project, Mapping):
            name = project.get("name") or project.get("title")
            tech = _strings(project.get("technologies") or project.get("tech_stack") or [], 10)
            if isinstance(name, str) and name.strip():
                projects.append({"name": name.strip()[:80], "tech": tech})
    safe = {
        "target_roles": _strings(prefs.get("target_roles")),
        "tech_stack": _strings(prefs.get("tech_stack")),
        "skills": _strings(profile.get("verified_skills")),
        "skill_years": skill_years,
        "total_experience_years": total,
        "notice_period_days": int(n) if (n := _number(prefs.get("notice_period_days"))) is not None else None,
        "remote_policy": prefs.get("remote_policy") if isinstance(prefs.get("remote_policy"), str) else None,
        "city": _city(prefs.get("current_location")),
        "willing_to_relocate": prefs.get("willing_to_relocate")
        if isinstance(prefs.get("willing_to_relocate"), bool) else None,
        "roles_held": _strings(profile.get("verified_roles"), 10),
        "projects": projects[:8],
    }
    return {k: v for k, v in safe.items() if v not in (None, [], {})}


# --- Phase 9C: reversible placeholders for the owner's own agent chat ------------------------------
# Square brackets (not <...>): the router strips anything that looks like an HTML tag before dispatch.
_PLACEHOLDER = re.compile(r"\[(?:PHONE|EMAIL|PRIVATE|CODE)_\d{1,3}\]")
_CODE = re.compile(r"(?<![\w.+-])\d{4,8}(?![\w.-])")


def scrub_with_map(text: str, secrets: Iterable[str] = (), *, mask_codes: bool = False,
                   allowed_email_domains: Iterable[str] = ()) -> tuple[str, dict[str, str]]:
    """Replace the phones / personal emails / explicit secrets the owner typed with numbered
    placeholders (``[PHONE_1]``, ``[EMAIL_1]``, ``[PRIVATE_1]``; ``[CODE_1]`` for 4-8 digit codes when
    ``mask_codes``) so an external LLM never sees them, plus the mapping to restore them locally.
    Anything else sensitive (tokens, PAN, Aadhaar, ...) is irreversibly redacted by `scrub_pii`."""
    if not text:
        return text, {}
    mapping: dict[str, str] = {}
    reverse: dict[tuple[str, str], str] = {}
    allowed = SAFE_EMAIL_DOMAINS | {d.lower().lstrip("@") for d in allowed_email_domains}

    def token(kind: str, value: str) -> str:
        key = (kind, value.lower() if kind == "EMAIL" else value)
        if key not in reverse:
            placeholder = f"[{kind}_{sum(1 for k in reverse if k[0] == kind) + 1}]"
            reverse[key] = placeholder
            mapping[placeholder] = value
        return reverse[key]

    # Whole emails and phones first (an owner name inside an address must not split it), then secrets.
    result = _EMAIL.sub(lambda m: m.group(0) if m.group(0).rsplit("@", 1)[-1].lower() in allowed
                        else token("EMAIL", m.group(0)), text)
    result = _PHONE.sub(lambda m: token("PHONE", m.group(0)), result)
    variants = sorted({v for s in secrets if isinstance(s, str) and s.strip() for v in _secret_variants(s)},
                      key=len, reverse=True)
    for secret in variants:
        result = re.sub(rf"(?<![\w@\[]){re.escape(secret)}(?![\w@\]])", lambda m: token("PRIVATE", m.group(0)),
                        result, flags=re.IGNORECASE)
    if mask_codes:
        result = _CODE.sub(lambda m: token("CODE", m.group(0)), result)
    return scrub_pii(result), mapping


def rehydrate(value: Any, mapping: Mapping[str, str]) -> Any:
    """Restore placeholders produced by `scrub_with_map` inside strings, lists and dict values."""
    if not mapping:
        return value
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: mapping.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [rehydrate(item, mapping) for item in value]
    if isinstance(value, tuple):
        return tuple(rehydrate(item, mapping) for item in value)
    if isinstance(value, dict):
        return {key: rehydrate(item, mapping) for key, item in value.items()}
    return value
