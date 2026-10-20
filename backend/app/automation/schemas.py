"""Owner-reviewed, bounded automation configuration."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.services.startup_discovery.source_registry import INTERVALS


class ScheduleConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    sources: list[Literal["hacker_news", "arbeitnow", "remotive", "greenhouse"]] = (
        Field(default_factory=list, max_length=4)
    )
    interval_seconds: int = Field(21600, ge=300, le=604800)
    limit: int = Field(20, ge=1, le=50)
    approved_profile_id: UUID | None = None
    approved_profile_version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def safe_intervals(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Duplicate sources")
        if any(self.interval_seconds < INTERVALS[s] for s in self.sources):
            raise ValueError("Schedule interval is below a source minimum")
        if bool(self.approved_profile_id) != bool(self.approved_profile_version):
            raise ValueError("Approval requires both profile identity and version")
        if self.enabled and not self.sources:
            raise ValueError("Choose permitted sources first")
        return self


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    configuration: ScheduleConfiguration


class ManualRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    expected_version: int = Field(ge=1)
