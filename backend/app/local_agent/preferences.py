"""Discovery preferences reuse profile contracts; no inferred job properties or execution."""
from typing import Literal

from pydantic import Field, model_validator

from backend.app.dashboard.models import OwnerPreference
from backend.app.schemas.candidate_profile import JobSearchPreferences


class SearchPreferences(JobSearchPreferences):
    minimum_experience: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    maximum_experience: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    maximum_salary: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    minimum_employees: int | None = Field(None, ge=1, le=10000000)
    maximum_employees: int | None = Field(None, ge=1, le=10000000)
    source_platforms: list[str] = Field(default_factory=list, max_length=20)
    posting_recency_days: int = Field(30, ge=1, le=365)
    relevance_threshold: float = Field(0, ge=0, le=100, allow_inf_nan=False)
    application_status: Literal["all", "applied", "not_applied"] = "not_applied"
    saved_jobs_only: bool = False
    require_known_properties: Literal[True] = True
    duplicate_prevention: Literal[True] = True

    @model_validator(mode="after")
    def ordered_ranges(self):
        for low, high in ((self.minimum_experience, self.maximum_experience), (self.minimum_salary, self.maximum_salary), (self.minimum_employees, self.maximum_employees)):
            if low is not None and high is not None and low > high:
                raise ValueError("minimum_exceeds_maximum")
        if any(not 1 <= len(value) <= 100 for value in self.source_platforms):
            raise ValueError("invalid_source_platform")
        return self


async def get_preferences(session):
    row = await session.get(OwnerPreference, "agent_search_preferences")
    return SearchPreferences.model_validate(row.value if row else {}).model_dump(mode="json")


async def save_preferences(session, preferences):
    row = await session.get(OwnerPreference, "agent_search_preferences", with_for_update=True)
    value = preferences.model_dump(mode="json")
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key="agent_search_preferences", value=value))
    await session.flush()
    return value
