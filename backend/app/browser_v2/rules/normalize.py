"""Text normalization, cross-portal dedup keys and target-role matching."""

from __future__ import annotations

import re

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
