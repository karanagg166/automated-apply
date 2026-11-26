"""Pydantic argument models for every agent tool (unknown keys are rejected)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.agent_v2.intent import PORTAL_ALIASES

APPLICATION_STATES = ("DISCOVERED", "FILTERED_OUT", "SCORED", "APPLYING", "WAITING_FOR_USER", "APPLIED",
                      "QUOTA_HIT_PENDING", "DRAFTED_AND_QUEUED", "SUBMISSION_UNKNOWN", "FAILED")
BOARD_PORTALS = ("greenhouse", "lever", "ashby", "smartrecruiters")


def portal_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = " ".join(value.strip().lower().replace("-", " ").split())
    return PORTAL_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoArgs(Args):
    pass


class PortalArg(Args):
    portal: str | None = Field(default=None, max_length=40)

    @field_validator("portal", mode="before")
    @classmethod
    def _portal(cls, value: Any) -> Any:
        return portal_name(value) if value else None


class QueryApplicationsArgs(PortalArg):
    status: Literal[APPLICATION_STATES] | None = None  # type: ignore[valid-type]
    company: str | None = Field(default=None, max_length=120)
    days: int = Field(default=7, ge=1, le=90)
    limit: int = Field(default=10, ge=1, le=25)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) and value.strip() else None


class ApplicationDetailsArgs(Args):
    app_id_or_company: str = Field(min_length=1, max_length=120)


class SearchCacheArgs(Args):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class AnalyticsArgs(PortalArg):
    days: int = Field(default=7, ge=1, le=90)


class UpdateProfileArgs(Args):
    fields: dict[str, Any] = Field(min_length=1, max_length=20)


class UpsertFactArgs(Args):
    question: str = Field(min_length=3, max_length=1000)
    answer: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="screening_qa", pattern=r"^[a-z][a-z0-9_]{1,39}$")


class RemoveFactArgs(Args):
    id: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-fA-F-]{8,64}$")


class UpdateRuleArgs(Args):
    portals: list[str] = Field(min_length=1, max_length=20)
    patch: dict[str, Any] = Field(default_factory=dict, max_length=20)
    boards_add: list[str] = Field(default_factory=list, max_length=25)
    boards_remove: list[str] = Field(default_factory=list, max_length=25)

    @field_validator("portals", mode="before")
    @classmethod
    def _portals(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = [value]
        return [portal_name(v) for v in value] if isinstance(value, list) else value

    @field_validator("boards_add", "boards_remove")
    @classmethod
    def _boards(cls, value: list[str]) -> list[str]:
        import re

        cleaned = [v.strip().lower() for v in value if isinstance(v, str) and v.strip()]
        bad = [v for v in cleaned if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,99}", v)]
        if bad:
            raise ValueError(f"invalid board slug: {bad[0][:40]}")
        return list(dict.fromkeys(cleaned))


class ControlWorkerArgs(PortalArg):
    action: Literal["pause", "resume", "run_once", "status", "sweep", "digest"]
    dry_run: bool | None = None


class EnqueueArgs(PortalArg):
    url: str = Field(min_length=12, max_length=2000, pattern=r"^https://\S+$")
    priority: Literal["P0", "P1", "P2", "P3"] = "P0"


class ResolveHitlArgs(Args):
    hitl_id_or_ref: str = Field(min_length=4, max_length=64, pattern=r"^[0-9a-fA-F-]{4,64}$")
    answer: str | None = Field(default=None, max_length=1000)
    action: Literal["answer", "skip", "retry"] = "answer"


class ProfileSyncArgs(Args):
    portals: list[str] = Field(min_length=1, max_length=15)
    dry_run: bool = True

    @field_validator("portals", mode="before")
    @classmethod
    def _portals(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = [value]
        return [portal_name(v) for v in value] if isinstance(value, list) else value
