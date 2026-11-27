"""Name the job's country inside geography-dependent screening questions.

"Are you authorized to work in the country in which this role is located?" and a bare "Will you
now or in the future require sponsorship?" mean different things for an India job and a US job.
Both the deterministic resolver and the semantic cache must see the country, and the HITL prompt
must carry it too, so an owner answer given for one country is never reused for another.
"""

from __future__ import annotations

import re

from backend.app.browser_v2.answers.classifier import SPONSORSHIP_Q, WORK_AUTH_Q
from backend.app.browser_v2.answers.geography import (
    COUNTRIES,
    countries_mentioned,
    place_facts,
)

ROLE_COUNTRY = re.compile(r"\b(?:the\s+)?country\s+(?:in\s+which|where)\s+(?:this|the)\s+(?:role|position|job)\s+is\s+"
                          r"(?:located|based)\b", re.IGNORECASE)
# Portals that only list jobs in India: their questionnaires are about Indian work authorization.
INDIA_ONLY_PORTALS = frozenset({"naukri", "internshala", "instahyre"})


def role_country(location: str | None) -> str | None:
    """Country of the job's own location ("Bengaluru, India" / "Pune" -> "India"); None when unclear."""
    if not location or re.search(r"\bremote\b", location, re.IGNORECASE) and "," not in location:
        return None
    place = place_facts(location, None, None)
    if not place.country_code:
        return None
    names = [name for _, (name, code) in COUNTRIES.items() if code == place.country_code]
    return names[0] if names else None


def job_country(location: str | None, platform: str | None = None) -> str | None:
    return role_country(location) or ("India" if (platform or "").lower() in INDIA_ONLY_PORTALS else None)


def is_geo_question(question: str) -> bool:
    return bool(WORK_AUTH_Q.search(question or "") or SPONSORSHIP_Q.search(question or ""))


def localize_question(question: str, country: str | None) -> str:
    """Substitute / append the job country for work-authorization and sponsorship questions.

    Idempotent: a question that already names a country (or has no country to add) is unchanged."""
    if not country or not question:
        return question
    if ROLE_COUNTRY.search(question):
        return ROLE_COUNTRY.sub(country, question)
    if is_geo_question(question) and not countries_mentioned(question):
        return f"{question.rstrip()} (job country: {country})"
    return question
