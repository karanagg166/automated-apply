"""Explicit multiple-choice sets; no model guesses or implicit negative facts."""

import json
import re

from sqlalchemy import text

from backend.app.core.config import get_settings
from backend.app.services.applications.base import ApplicationInvalid


def decode(answer, options, *, required):
    try:
        selected = json.loads(answer)
    except (ValueError, TypeError):
        raise ValueError("Supply a JSON array of exact displayed options") from None
    if (
        not isinstance(selected, list)
        or len(selected) > 50
        or (required and not selected)
        or any(not isinstance(item, str) or item not in options for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError(
            "Select distinct exact form options; required sets cannot be empty"
        )
    return selected


def encode(values):
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def verified_choices(question, profile):
    # A skill alone establishes no duration, proficiency, certification or employment.
    title = re.sub(r"\s+", " ", question.strip().lower()).rstrip(" *?.:")
    title = re.sub(r"\s*\((?:select|choose|check) all that apply\)$", "", title).strip()
    if title not in {
        "skills",
        "technical skills",
        "select technical skills",
        "select your technical skills",
        "select all technical skills that apply",
        "which technical skills do you have",
        "programming languages",
    }:
        return set()
    facts = {skill.casefold() for skill in profile.verified_skills}
    return facts


async def available(session):
    settings = get_settings()
    if not settings.MULTI_SELECT_FIELDS_ENABLED:
        return False
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        return settings.ENVIRONMENT == "testing"
    if dialect != "postgresql":
        return False
    # Read capability and privilege only. Never install SQL or infer activation
    # from a flag, an API key or an employer URL.
    return bool(
        await session.scalar(
            text("""
        SELECT EXISTS (
          SELECT 1 FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid=c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
          JOIN pg_catalog.pg_proc p ON p.pronamespace=n.oid
          WHERE n.nspname=:schema AND t.relname='application_packet_fields'
            AND c.conname='ck_application_fields_multi_select_v1' AND c.convalidated
            AND p.proname='valid_multi_select_answer' AND p.pronargs=3
            AND pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE')
        )
    """),
            {"schema": settings.DATABASE_SCHEMA},
        )
    )


async def require_available(session):
    if not await available(session):
        raise ApplicationInvalid(
            "Multiple selections require explicit enablement and an installed, permitted database capability; use manual handoff"
        )
