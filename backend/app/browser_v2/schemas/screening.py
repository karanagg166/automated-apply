"""Screening facts (subset of JobSearchPreferences) read/patch contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from backend.app.schemas.candidate_profile import JobSearchPreferences

SCREENING_FIELDS = (
    "target_roles", "keywords_required", "keywords_excluded", "tech_stack", "company_blacklist",
    "remote_policy", "skill_match_mode", "min_match_score", "current_ctc", "expected_ctc", "min_ctc",
    "notice_period_days", "total_experience_years", "current_location", "willing_to_relocate",
    "skill_years", "country", "current_company", "current_title", "english_proficiency",
    # Phase 9B
    "max_required_experience_years", "headline", "internship_months", "graduation_month",
    "open_to_internships", "notify_early_bird",
)


class _ScreeningBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# Field types/constraints are copied from JobSearchPreferences so both APIs validate identically.
_fields: dict[str, Any] = {
    name: (JobSearchPreferences.model_fields[name].rebuild_annotation(),
           JobSearchPreferences.model_fields[name])
    for name in SCREENING_FIELDS
}
ScreeningFacts = create_model("ScreeningFacts", __base__=_ScreeningBase, **_fields)


class ScreeningProfileRead(ScreeningFacts):  # type: ignore[misc, valid-type]
    version: int = Field(description="candidate_profiles.version; send back on PATCH")
    has_profile: bool = True


_patch_fields: dict[str, Any] = {
    name: (JobSearchPreferences.model_fields[name].rebuild_annotation(), None) for name in SCREENING_FIELDS
}
_ScreeningPatchBase = create_model(
    "_ScreeningPatchBase", __base__=_ScreeningBase, **_patch_fields)


class ScreeningProfilePatch(_ScreeningPatchBase):  # type: ignore[misc, valid-type]
    version: int = Field(ge=1, description="Current candidate_profiles.version")

    @model_validator(mode="after")
    def require_change(self) -> ScreeningProfilePatch:
        if not (self.model_fields_set - {"version"}):
            raise ValueError("Supply at least one screening fact to change")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(mode="json", include=self.model_fields_set - {"version"})
