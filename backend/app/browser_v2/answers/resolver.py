"""Tier-0 screening resolver: exact answers from verified facts, else None (HITL)."""

from __future__ import annotations

from backend.app.browser_v2.answers.classifier import (
    BLOCKED,
    CITY_Q,
    COUNTRY_Q,
    CURRENT_COMPANY_Q,
    CURRENT_CTC,
    CURRENT_LOCATION,
    CURRENT_TITLE_Q,
    ENGLISH_Q,
    EXPECTED_CTC,
    GENERIC_FIELDS,
    IMMEDIATE_JOINER,
    JOIN_WITHIN,
    LOCATED_IN,
    NOTICE,
    RELOCATE,
    RELOCATE_TARGET,
    SENSITIVE,
    SKILL_EXPERIENCE,
    SKILL_YES_NO,
    START_WHEN,
    STATE_Q,
    TOTAL_EXPERIENCE,
)
from backend.app.browser_v2.answers.deterministic import (
    _authorization_answer,
    _link_answer,
    _numeric_option,
    _threshold_answer,
    _yes_no_only,
    choose_notice,
    choose_text_option,
    ctc_answer,
)
from backend.app.browser_v2.answers.education import education_answer
from backend.app.browser_v2.answers.facts import CandidateFacts
from backend.app.browser_v2.answers.geography import (
    _same_place,
    choose_country,
    choose_place,
    place_match,
)
from backend.app.browser_v2.answers.normalizers import (
    _years,
    choose_option,
    choose_yes_no,
    normalize,
)
from backend.app.browser_v2.tech_terms import is_known_tech


def resolve_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> str | None:
    """Return an exact option/text answer, or None when a human must answer."""
    if BLOCKED.search(question) or SENSITIVE.search(question):
        return None
    saved = facts.saved_answers.get(normalize(question))
    if saved:
        return choose_option(options, saved)
    handled_education, education = education_answer(question, options, facts.education)
    if handled_education:
        return education
    if facts.notice_period_days is not None:
        within = JOIN_WITHIN.search(question)
        if within:
            unit = within.group("unit").lower()
            limit = int(within.group("n")) * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)
            return choose_yes_no(options, facts.notice_period_days <= limit)
        if IMMEDIATE_JOINER.search(question) and (not options or _yes_no_only(options)):
            return choose_yes_no(options, facts.notice_period_days == 0)
        if NOTICE.search(question):
            return choose_notice(options, facts.notice_period_days)
        if START_WHEN.search(question):
            if options:
                return choose_notice(options, facts.notice_period_days)
            return "Immediately" if facts.notice_period_days == 0 else f"Within {facts.notice_period_days} days"
    if CURRENT_CTC.search(question):
        return ctc_answer(question, options, facts.current_ctc)
    if EXPECTED_CTC.search(question):
        return ctc_answer(question, options, facts.expected_ctc)
    handled, answer = _authorization_answer(question, options, facts)
    if handled:
        return answer
    located = LOCATED_IN.search(question)
    if located:
        matched = place_match(located.group("city"), facts)
        if matched is not None:
            return choose_yes_no(options, matched)
        if not facts.current_location:
            return None
    if COUNTRY_Q.search(question):
        return choose_country(options, facts.country, facts.country_code) if facts.country else None
    if STATE_Q.search(question):
        return choose_place(options, facts.state) if facts.state else None
    if CITY_Q.search(question):
        return choose_place(options, facts.city) if facts.city else None
    if CURRENT_LOCATION.search(question):
        return choose_place(options, facts.current_location) if facts.current_location else None
    if CURRENT_COMPANY_Q.search(question):
        return choose_text_option(options, facts.current_company) if facts.current_company else None
    if CURRENT_TITLE_Q.search(question):
        return choose_text_option(options, facts.current_title) if facts.current_title else None
    if ENGLISH_Q.search(question):
        return choose_text_option(options, facts.english_proficiency) if facts.english_proficiency else None
    handled, answer = _link_answer(question, options, facts)
    if handled:
        return answer
    if RELOCATE.search(question):
        target = RELOCATE_TARGET.search(question)
        if target:
            place = target.group("city")
            if place_match(place, facts) or any(_same_place(place, loc) for loc in facts.relocation_locations):
                return choose_yes_no(options, True)
        if facts.willing_to_relocate is not None:
            return choose_yes_no(options, facts.willing_to_relocate)
        return None
    handled, answer = _threshold_answer(question, options, facts)
    if handled:
        return answer
    skill_match = SKILL_EXPERIENCE.search(question) or SKILL_YES_NO.search(question)
    if skill_match and normalize(skill_match.group("skill")) in GENERIC_FIELDS:
        skill_match = None
    if options and _yes_no_only(options) and skill_match:
        skill = skill_match.group("skill")
        if facts.has_skill(skill):
            return choose_yes_no(options, True)
        # "No" only for a recognizable technology; "comfortable with on-call rotations?" is not a
        # skill, so it falls through to the cache / LLM / human instead of a fabricated "No".
        return choose_yes_no(options, False) if is_known_tech(skill) else None
    if skill_match:
        years = facts.skill_years.get(normalize(skill_match.group("skill")))
        if years is None:
            return None
        return _numeric_option(options, years) if options else _years(years)
    if TOTAL_EXPERIENCE.search(question) and facts.experience_years is not None:
        return (_numeric_option(options, facts.experience_years) if options
                else _years(facts.experience_years))
    return None
