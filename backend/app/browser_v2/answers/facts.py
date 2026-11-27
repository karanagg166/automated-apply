"""Verified candidate facts built from the stored profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.browser_v2.answers.education import education_from_profile
from backend.app.browser_v2.answers.geography import country_of, place_facts
from backend.app.browser_v2.answers.normalizers import (
    _float,
    _int,
    _text,
    _years,
    normalize,
)

IDENTITY_KEYS = ("full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url",
                 "personal_website")


def identity_fields(profile: dict[str, Any]) -> dict[str, str]:
    """Stored identity values only (first/last name split from full_name); never invented."""
    values = {key: profile[key].strip() for key in IDENTITY_KEYS
              if isinstance(profile.get(key), str) and profile[key].strip()}
    prefs = profile.get("preferences") or {}
    location = prefs.get("current_location") if isinstance(prefs, dict) else None
    if isinstance(location, str) and location.strip():
        values["current_location"] = location.strip()
    name = values.get("full_name", "")
    if name:
        first, _, last = name.partition(" ")
        values["first_name"] = first
        if last.strip():
            values["last_name"] = last.strip()
    if "portfolio_url" not in values and "personal_website" in values:
        values["portfolio_url"] = values["personal_website"]
    return values


@dataclass(frozen=True)
class WorkAuthorization:
    country_code: str
    authorized: bool | None
    requires_sponsorship: bool | None


def _work_authorizations(value: Any) -> tuple[WorkAuthorization, ...]:
    rows: list[WorkAuthorization] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        code = item.get("country_code")
        if not isinstance(code, str) or not code.strip():
            found = country_of(str(item.get("country_name") or ""))
            code = found[1] if found else None
        if code:
            authorized = item.get("authorized_to_work")
            sponsor = item.get("requires_sponsorship_now_or_future")
            rows.append(WorkAuthorization(code.strip().upper(), authorized if isinstance(authorized, bool) else None,
                                          sponsor if isinstance(sponsor, bool) else None))
    return tuple(rows)


def _lpa_from_compensation(value: Any) -> str | None:
    """INR yearly CTC fact (preferences.*_compensation) -> LPA text; other currencies/periods: None."""
    if not isinstance(value, dict) or value.get("currency") != "INR" or value.get("period") != "year" \
            or value.get("kind") not in ("ctc", "total_compensation"):
        return None
    amount = _float(value.get("amount"))
    return _years(amount / 100_000) if amount is not None and amount >= 0 else None


@dataclass
class CandidateFacts:
    experience_years: float | None = None
    skills: tuple[str, ...] = ()
    skill_years: dict[str, float] = field(default_factory=dict)
    notice_period_days: int | None = None
    current_ctc: str | None = None  # LPA ("12" or legacy free text like "8 LPA")
    expected_ctc: str | None = None
    current_location: str | None = None
    willing_to_relocate: bool | None = None
    saved_answers: dict[str, str] = field(default_factory=dict)
    # Phase 6A: identity fields typed deterministically into hosted ATS forms (never sent
    # to an LLM) and the owner's local resume PDFs (preferences.resume_files).
    identity: dict[str, str] = field(default_factory=dict)
    resume_files: dict[str, Any] = field(default_factory=dict)
    # Workstream 3: place / employer / authorization facts (stored or deterministically derived).
    city: str | None = None
    state: str | None = None
    country: str | None = None
    country_code: str | None = None
    country_source: str | None = None
    relocation_locations: tuple[str, ...] = ()
    current_company: str | None = None
    current_title: str | None = None
    work_authorization: str | None = None
    work_authorizations: tuple[WorkAuthorization, ...] = ()
    english_proficiency: str | None = None
    education: Any = None  # Phase 9: answers.education.Education from candidate_profiles.education

    @classmethod
    def from_profile(cls, profile: dict[str, Any],
                     reviewed_answers: list[tuple[str, str]] | None = None) -> CandidateFacts:
        prefs = profile.get("preferences") or {}
        if not isinstance(prefs, dict):
            prefs = {}
        skills = []
        for item in profile.get("verified_skills") or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                skills.append(name.strip())
        skill_years: dict[str, float] = {}
        for key, value in (prefs.get("skill_years") or {}).items():
            years = _float(value)
            if isinstance(key, str) and normalize(key) and years is not None:
                skill_years[normalize(key)] = years
        total = _float(prefs.get("total_experience_years"))
        location = _text(prefs.get("current_location"))
        place = place_facts(location, _text(prefs.get("country") or profile.get("country")),
                            _text(profile.get("phone")))
        # willing_to_relocate (v2 key) wins; the dashboard's open_to_relocation is the same fact.
        relocate = next((prefs.get(k) for k in ("willing_to_relocate", "open_to_relocation")
                         if isinstance(prefs.get(k), bool)), None)
        identity = identity_fields(profile)
        company = _text(prefs.get("current_company") or profile.get("current_company"))
        for key, value in (("city", place.city), ("state", place.state), ("country", place.country),
                           ("current_company", company)):
            if value:
                identity.setdefault(key, value)
        # Only explicitly stored facts: never derive expected CTC from min_ctc.
        return cls(
            education=education_from_profile(profile),
            experience_years=total if total is not None else _float(profile.get("verified_experience_years")),
            skills=tuple(skills),
            skill_years=skill_years,
            notice_period_days=_int(prefs.get("notice_period_days")),
            current_ctc=_text(prefs.get("current_ctc")) or _lpa_from_compensation(prefs.get("current_compensation")),
            expected_ctc=_text(prefs.get("expected_ctc"))
            or _lpa_from_compensation(prefs.get("expected_compensation")),
            current_location=location,
            willing_to_relocate=relocate,
            saved_answers={normalize(q): a for q, a in reviewed_answers or []},
            identity=identity,
            resume_files=dict(prefs.get("resume_files") or {}) if isinstance(prefs.get("resume_files"), dict)
            else {},
            city=place.city, state=place.state, country=place.country, country_code=place.country_code,
            country_source=place.country_source,
            relocation_locations=tuple(x.strip() for x in prefs.get("relocation_locations") or ()
                                       if isinstance(x, str) and x.strip()),
            current_company=company,
            current_title=_text(prefs.get("current_title")),
            work_authorization=_text(prefs.get("work_authorization")),
            work_authorizations=_work_authorizations(prefs.get("work_authorizations")),
            english_proficiency=_text(prefs.get("english_proficiency")),
        )

    def has_skill(self, skill: str) -> bool:
        wanted = normalize(skill)
        if self.skill_years.get(wanted, 0) > 0:
            return True
        return any(normalize(s) == wanted for s in self.skills)
