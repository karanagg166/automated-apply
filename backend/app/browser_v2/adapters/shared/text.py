"""Shared adapter constants, text helpers, answer resolution and the deterministic intro."""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from backend.app.browser_v2.adapters.base import JobDetail
from backend.app.browser_v2.answers import (
    CandidateFacts,
    ScreeningResolver,
    hitl_override,
    resolve_answer,
)
from backend.app.browser_v2.state import ApplicationState

S = ApplicationState
MAX_DESCRIPTION = 8_000
MAX_FORM_STEPS = 6


def html_to_text(value: str | None, limit: int = MAX_DESCRIPTION) -> str | None:
    """Plain bounded text from (possibly entity-escaped) HTML. Never returns markup."""
    if not value:
        return None
    text = html.unescape(html.unescape(value))
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit] or None


def age_days_from(value: datetime | None, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return max(((now or datetime.now(UTC)) - moment).days, 0)


def role_query_match(title: str | None, query: str | None) -> bool:
    """Every meaningful query word (seniority-insensitive, engineer~developer) is in the title."""
    from backend.app.browser_v2.rules import _role_matches

    if not query or not query.strip():
        return True
    # Phase 9: "Backend Engineer | AI Engineer | ..." matches any of the owner's target roles at once.
    roles = [part.strip() for part in query.split(ROLE_QUERY_SEPARATOR) if part.strip()]
    return bool(title) and any(_role_matches(title or "", role) for role in roles)


ROLE_QUERY_SEPARATOR = "|"


def multi_role_query(roles: list[str] | tuple[str, ...]) -> str:
    """One discovery query that matches every target role (whole-feed adapters only)."""
    return f" {ROLE_QUERY_SEPARATOR} ".join(role.strip() for role in roles if role and role.strip())


# --- shared answer resolution ---------------------------------------------------------------
async def resolve_question(question: str, options: tuple[str, ...], facts: CandidateFacts, detail: JobDetail,
                           answerer: ScreeningResolver | None, hitl_answers: dict[str, str] | None
                           ) -> tuple[str | None, str, str]:
    owner = hitl_override(question, options, hitl_answers)
    if owner is not None:
        return owner, "human_hitl", "hitl_owner_answer"
    if answerer is None:
        answer = resolve_answer(question, options, facts)
        return answer, "profile" if answer is not None else "human", "deterministic_only"
    resolved = await answerer.resolve(question, options, facts, {
        "title": detail.listing.title, "company": detail.listing.company})
    return resolved.answer, resolved.source, resolved.reason


NoteComposer = Callable[[JobDetail, CandidateFacts], Awaitable[str | None]]
COVER_NOTE = re.compile(
    r"cover letter|cover note|why should (?:we|you) (?:be )?hire|why (?:are you|do you want)|"
    r"\b(?:write|add|send|include)?\s*(?:a |an )?(?:short |brief )?(?:note|message) to\b|"
    r"introduce yourself|short (?:note|intro)|tell (?:us|the team) (?:about yourself|why)|add a note|"
    r"what interests you", re.IGNORECASE)


def deterministic_intro(detail: JobDetail, facts: CandidateFacts) -> str | None:
    """Template intro from verified facts only (no invented employers, dates or numbers)."""
    skills = [s for s in facts.skills][:5]
    if not skills and facts.experience_years is None:
        return None
    role = detail.listing.title or "this role"
    company = detail.listing.company or "your team"
    parts = [f"Hi {company} team, I'm interested in the {role} position."]
    if facts.experience_years is not None:
        years = int(facts.experience_years) if float(facts.experience_years).is_integer() \
            else facts.experience_years
        parts.append(f"I have {years} year{'s' if facts.experience_years != 1 else ''} of experience")
        parts[-1] += f" working with {', '.join(skills)}." if skills else "."
    elif skills:
        parts.append(f"I work with {', '.join(skills)}.")
    parts.append("I'd be glad to share more details about my work and how I can contribute.")
    return " ".join(parts)
