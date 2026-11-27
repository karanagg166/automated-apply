"""Candidate screening-fact tooling (Workstream 3): report, set and re-seed.

    facts report                 which canonical facts are present / missing (values masked)
    facts set <key> <value>      validated write into candidate_profiles.preferences
    facts reseed-cache           idempotent reviewed-answer import into semantic_cache
    facts stamp-cache            one-time after followup 006: owner-verified answers get the current
                                 profile_version_hash (else every pre-006 factual answer counts as stale)

Values are never printed in clear (phone, e-mail, CTC, location are PII). Writes go
through `store.update_preferences`, i.e. the same `JobSearchPreferences` validation as
the dashboard; keys the schema does not have are refused with `schema_field_required`
instead of being smuggled into another field.

Wire into cli.py with:
    from backend.app.browser_v2 import facts_cli
    facts_cli.register(commands)                       # in build_parser()
    if args.command == "facts": return facts_cli.run(args)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections.abc import Callable
from typing import Any

from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.answers.facts import DISCLOSURE_KEYS

# canonical fact -> where it comes from (for the report).
CANONICAL_FACTS: dict[str, str] = {
    "full_name": "profile.full_name",
    "email": "profile.email",
    "phone": "profile.phone",
    "linkedin_url": "profile.linkedin_url",
    "github_url": "profile.github_url",
    "portfolio_url": "profile.portfolio_url | profile.personal_website",
    "current_location": "preferences.current_location",
    "city": "derived from preferences.current_location",
    "state": "derived from preferences.current_location",
    "country": "preferences.country | current_location | phone +91",
    "willing_to_relocate": "preferences.willing_to_relocate | preferences.open_to_relocation",
    "work_authorization": "preferences.work_authorization | preferences.work_authorizations",
    "notice_period_days": "preferences.notice_period_days",
    "current_ctc": "preferences.current_ctc | preferences.current_compensation (INR/year)",
    "expected_ctc": "preferences.expected_ctc | preferences.expected_compensation (INR/year)",
    "total_experience_years": "preferences.total_experience_years | profile.verified_experience_years",
    "current_company": "preferences.current_company",
    "current_title": "preferences.current_title",
    "english_proficiency": "preferences.english_proficiency",
    "skill_years": "preferences.skill_years",
    "resume_files": "preferences.resume_files",
    # Owner-declared EEO / consent / NDA answers (answers/disclosures.py), e.g. disclosures.gender.
    **{f"disclosures.{key}": f"preferences.screening_disclosures.{key}" for key in DISCLOSURE_KEYS},
}


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("yes", "y", "true", "1"):
        return True
    if value in ("no", "n", "false", "0"):
        return False
    raise ValueError("expected yes/no")


def _parse_float(raw: str) -> float:
    number = float(raw.strip())
    if not math.isfinite(number):
        raise ValueError("expected a finite number")
    return number


def _parse_int(raw: str) -> int:
    return int(raw.strip())


def _parse_text(raw: str) -> str:
    text = " ".join(raw.split())
    if not text:
        raise ValueError("expected non-empty text")
    return text


def _parse_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


# Whitelisted canonical keys -> (preferences field, parser). Nothing else is writable here.
SETTABLE: dict[str, tuple[str, Callable[[str], Any]]] = {
    "current_location": ("current_location", _parse_text),
    "country": ("country", _parse_text),
    "current_company": ("current_company", _parse_text),
    "current_title": ("current_title", _parse_text),
    "english_proficiency": ("english_proficiency", _parse_text),
    "notice_period_days": ("notice_period_days", _parse_int),
    "current_ctc": ("current_ctc", _parse_float),
    "expected_ctc": ("expected_ctc", _parse_float),
    "total_experience_years": ("total_experience_years", _parse_float),
    "willing_to_relocate": ("willing_to_relocate", _parse_bool),
    "relocation_locations": ("relocation_locations", _parse_list),
    "work_authorization": ("work_authorization", _parse_text),
    # Phase 9B
    "max_required_experience_years": ("max_required_experience_years", _parse_float),
    "headline": ("headline", _parse_text),
    "internship_months": ("internship_months", _parse_int),
    "graduation_month": ("graduation_month", _parse_text),
    "open_to_internships": ("open_to_internships", _parse_bool),
    "notify_early_bird": ("notify_early_bird", _parse_bool),
}


def schema_fields() -> frozenset[str]:
    from backend.app.schemas.candidate_profile import JobSearchPreferences

    return frozenset(JobSearchPreferences.model_fields)


def mask(value: Any) -> str:
    """Presence hint only: booleans are shown, everything else is masked."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list, tuple)):
        return f"<{len(value)} item{'s' if len(value) != 1 else ''}>"
    text = str(value)
    return (text[:1] + "•" * min(max(len(text) - 1, 3), 8)) if text else ""


def _canonical_values(facts: CandidateFacts) -> dict[str, Any]:
    identity = facts.identity
    work_auth: Any = facts.work_authorization or (list(facts.work_authorizations) or None)
    return {
        "full_name": identity.get("full_name"),
        "email": identity.get("email"),
        "phone": identity.get("phone"),
        "linkedin_url": identity.get("linkedin_url"),
        "github_url": identity.get("github_url"),
        "portfolio_url": identity.get("portfolio_url"),
        "current_location": facts.current_location,
        "city": facts.city,
        "state": facts.state,
        "country": facts.country,
        "willing_to_relocate": facts.willing_to_relocate,
        "work_authorization": work_auth,
        "notice_period_days": facts.notice_period_days,
        "current_ctc": facts.current_ctc,
        "expected_ctc": facts.expected_ctc,
        "total_experience_years": facts.experience_years,
        "current_company": facts.current_company,
        "current_title": facts.current_title,
        "english_proficiency": facts.english_proficiency,
        "skill_years": facts.skill_years or None,
        "resume_files": facts.resume_files or None,
        **{f"disclosures.{key}": facts.disclosures.get(key) for key in DISCLOSURE_KEYS},
    }


async def facts_report(store: Any) -> dict[str, Any]:
    """Which canonical screening facts are present / missing (values masked, never in clear)."""
    profile, reviewed = await store.load_profile()
    if not profile:
        return {"profile": "missing", "present": [], "missing": list(CANONICAL_FACTS),
                "reviewed_answers": len(reviewed)}
    facts = CandidateFacts.from_profile(profile, reviewed)
    values = _canonical_values(facts)
    present = [key for key, value in values.items() if value not in (None, "", [], {})]
    missing = [key for key in CANONICAL_FACTS if key not in present]
    fields = schema_fields()
    return {
        "profile": "present",
        "present": present,
        "missing": missing,
        "masked": {key: mask(values[key]) for key in present},
        "sources": {key: CANONICAL_FACTS[key] for key in missing},
        "derived": {"country": facts.country_source} if facts.country else {},
        "needs_schema_field": sorted(key for key, (pref, _) in SETTABLE.items() if pref not in fields),
        "reviewed_answers": len(reviewed),
    }


async def set_fact(store: Any, key: str, value: str) -> dict[str, Any]:
    """Validated write of one whitelisted canonical fact into candidate_profiles.preferences."""
    if key not in SETTABLE:
        return {"ok": False, "key": key, "error": "key_not_allowed", "allowed": sorted(SETTABLE)}
    field_name, parse = SETTABLE[key]
    if field_name not in schema_fields():
        return {"ok": False, "key": key, "error": "schema_field_required",
                "detail": f"JobSearchPreferences has no '{field_name}' field; add it to "
                          "backend/app/schemas/candidate_profile.py before storing this fact"}
    try:
        parsed = parse(value)
    except ValueError as exc:
        return {"ok": False, "key": key, "error": f"invalid_value: {exc}"}
    try:
        stored = await store.update_preferences({field_name: parsed})
    except ValueError as exc:  # JobSearchPreferences validation
        return {"ok": False, "key": key, "error": str(exc)}
    except LookupError as exc:  # ProfileMissing
        return {"ok": False, "key": key, "error": str(exc) or type(exc).__name__}
    return {"ok": True, "key": key, "field": f"preferences.{field_name}", "stored": mask(stored.get(field_name))}


async def reseed_cache(store: Any, ai: Any) -> dict[str, Any]:
    """Idempotently import reviewed application_answer_drafts into semantic_cache (source='profile')."""
    from backend.app.ai_v2.semantic_cache import seed_semantic_cache

    _, reviewed = await store.load_profile()
    counts = await seed_semantic_cache(ai.cache, reviewed)
    return {"cache_backend": ai.cache.store.backend, **counts}


async def stamp_cache(store: Any, ai: Any, env: dict[str, str]) -> dict[str, Any]:
    """Stamp pre-006 owner-verified cache rows (source user/profile, no hash yet) with the hash the
    worker computes now - the same facts build as `ApplyMixin.process_job` (profile + .env overrides)."""
    from backend.app.ai_v2.semantic_cache.keys import profile_version_hash
    from backend.app.browser_v2.service.helpers import (
        apply_env_profile,
        env_profile_overrides,
    )

    connection = getattr(getattr(getattr(ai, "cache", None), "store", None), "connection", None)
    if connection is None:
        return {"ok": False, "error": "postgres semantic cache required (DATABASE_URL)"}
    profile, reviewed = await store.load_profile()
    facts = apply_env_profile(CandidateFacts.from_profile(profile, reviewed), env_profile_overrides(env))
    digest = profile_version_hash(facts)
    result = await connection.execute(
        """UPDATE public.semantic_cache SET profile_version_hash=$1, updated_at=now()
           WHERE profile_version_hash IS NULL AND status='active' AND source IN ('user','profile')""", digest)
    return {"ok": True, "stamped": int(str(result).rsplit(" ", 1)[-1] or 0), "profile_hash": (digest or "")[:12]}


# --- argparse wiring (cli.py imports these; this module never edits cli.py) ---------------
def register(subparsers: Any) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "facts", help="screening facts: report present/missing (masked), set one, reseed semantic cache")
    actions = parser.add_subparsers(dest="facts_action", required=True)
    actions.add_parser("report", help="canonical facts present / missing (values masked)")
    setter = actions.add_parser("set", help="store one whitelisted fact in candidate_profiles.preferences")
    setter.add_argument("key", choices=sorted(SETTABLE))
    setter.add_argument("value")
    actions.add_parser("reseed-cache", help="idempotent reviewed-answer import into semantic_cache")
    actions.add_parser("stamp-cache", help="after followup 006: stamp owner-verified answers with the current "
                                           "profile hash (they would count as stale otherwise)")
    return parser


async def _run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from backend.app.browser_v2.service import open_store

    action = args.facts_action
    store, backend = await open_store(require_db=action == "set")
    try:
        if action == "report":
            result = await facts_report(store)
        elif action == "set":
            result = await set_fact(store, args.key, args.value)
        elif action == "reseed-cache":
            from backend.app.ai_v2.runtime import AIRuntime

            result = await reseed_cache(store, await AIRuntime.for_store(store))
        elif action == "stamp-cache":
            from backend.app.ai_v2.runtime import AIRuntime
            from backend.app.browser_v2.env_loader import load_env

            result = await stamp_cache(store, await AIRuntime.for_store(store), load_env())
        else:
            return 2, {"error": f"unknown facts action: {action}"}
    finally:
        await store.close()
    result = {"store": backend.split(" ")[0], **result}
    return (0 if result.get("ok", True) else 1), result


def run(args: argparse.Namespace) -> int:
    code, result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, default=str))
    return code
