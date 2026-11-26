"""Canonical ProfileSnapshot: what every portal profile should say.

Source of truth is ``candidate_profiles`` (via ``store.load_profile()``):
- resume_headline      <- preferences.headline
- profile_summary      <- preferences.summary | preferences.profile_summary | profile.summary
- key_skills           <- preferences.tech_stack + preferences.skills + profile.verified_skills
- notice_period        <- preferences.notice_period_days (days)
- current/expected_ctc <- preferences.current_ctc / expected_ctc (INR LPA)
- preferred_locations  <- preferences.preferred_locations (+ relocation_locations when open to relocation)
- current_location     <- preferences.current_location
- resume_pdf           <- the active resume (``browser_v2.resume.pick_resume``): path + SHA-256
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.app.browser_v2.profile_sync.diff import clean_list, clean_text
from backend.app.browser_v2.profile_sync.models import ProfileSnapshot
from backend.app.browser_v2.resume import pick_resume

MAX_RESUME_BYTES = 5 * 1024 * 1024


def _number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _strings(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, (list, tuple)) else []


def file_sha256(path: str | None) -> str | None:
    """SHA-256 of a local resume PDF (None when missing, unreadable, too big or not a PDF)."""
    if not path:
        return None
    try:
        data = Path(path).expanduser().read_bytes()
    except OSError:
        return None
    if not data.startswith(b"%PDF-") or len(data) > MAX_RESUME_BYTES:
        return None
    return hashlib.sha256(data).hexdigest()


def preferences_of(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    prefs = profile.get("preferences")
    return prefs if isinstance(prefs, Mapping) else {}


def canonical_values(profile: Mapping[str, Any]) -> dict[str, Any]:
    prefs = preferences_of(profile)
    summary = prefs.get("summary") or prefs.get("profile_summary") or profile.get("summary")
    skills = clean_list([*_strings(prefs.get("tech_stack")), *_strings(prefs.get("skills")),
                         *_strings(profile.get("verified_skills"))])
    locations = _strings(prefs.get("preferred_locations"))
    if prefs.get("open_to_relocation") is True or prefs.get("willing_to_relocate") is True:
        locations += _strings(prefs.get("relocation_locations"))
    notice = prefs.get("notice_period_days")
    return {
        "resume_headline": clean_text(prefs.get("headline")),
        "profile_summary": clean_text(summary) if isinstance(summary, str) else None,
        "key_skills": skills,
        "notice_period": int(notice) if isinstance(notice, int) and not isinstance(notice, bool)
        and notice >= 0 else None,
        "current_ctc": _number(prefs.get("current_ctc")),
        "expected_ctc": _number(prefs.get("expected_ctc")),
        "preferred_locations": clean_list(locations),
        "current_location": clean_text(prefs.get("current_location")),
    }


def snapshot_from_profile(profile: Mapping[str, Any], *, fallback_resume_path: str | None = None,
                          check_files: bool = True) -> ProfileSnapshot:
    values = canonical_values(profile)
    prefs = preferences_of(profile)
    resume_files = prefs.get("resume_files") if isinstance(prefs.get("resume_files"), Mapping) else None
    choice = pick_resume(resume_files, title=None, description=None, fallback_path=fallback_resume_path,
                         check_files=check_files)
    sha = file_sha256(choice.path)
    values["resume_pdf"] = {"path": choice.path, "sha256": sha} if choice.path and sha else None
    return ProfileSnapshot(values=values, resume_path=choice.path if sha else None, resume_sha256=sha,
                           preferences=dict(prefs))


async def build_snapshot(store: Any, *, fallback_resume_path: str | None = None,
                         check_files: bool = True) -> ProfileSnapshot:
    profile, _ = await store.load_profile()
    return snapshot_from_profile(profile or {}, fallback_resume_path=fallback_resume_path,
                                 check_files=check_files)
