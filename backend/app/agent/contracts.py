"""Model proposals cannot carry identity, approval grants or execution flags."""
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from backend.app.local_agent.contracts import StrictModel

Intent = Literal["search", "filter", "apply", "status", "cancel", "approve", "select_project", "clarify"]
ToolName = Literal[
    "search_jobs", "filter_jobs", "rank_jobs", "get_candidate_profile",
    "get_approved_project_context", "get_canonical_resume", "get_application_history",
    "prepare_application", "generate_grounded_answer", "preview_application",
    "fill_application", "submit_application", "get_campaign_status", "cancel_campaign",
    "find_founder_profiles", "create_outreach_draft",
]
CampaignState = Literal["created", "planned", "awaiting_approval", "queued", "running",
                        "completed", "partially_completed", "failed", "cancelled"]


class Filters(StrictModel):
    role: str | None = Field(None, min_length=1, max_length=100)
    location: str | None = Field(None, min_length=1, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=10)
    remote: Literal["remote", "hybrid", "onsite", "any"] | None = None
    startup: bool = False
    minimum_employees: int | None = Field(None, ge=1, le=10000000)
    maximum_employees: int | None = Field(None, ge=1, le=10000000)
    minimum_experience: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    maximum_experience: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    minimum_salary: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_currency: str | None = Field(None, min_length=3, max_length=10)
    salary_period: Literal["year", "month", "hour"] | None = None
    exclude_applied: bool = True
    exclude_internships: bool = False
    source: Literal["cached", "greenhouse", "arbeitnow", "remotive", "hacker_news",
                    "naukri", "wellfound", "instahyre", "work_at_a_startup", "internshala"] = "cached"
    limit: int = Field(10, ge=1, le=10)

    @model_validator(mode="after")
    def ordered(self):
        for low, high in ((self.minimum_employees, self.maximum_employees),
                          (self.minimum_experience, self.maximum_experience)):
            if low is not None and high is not None and low > high:
                raise ValueError("minimum_exceeds_maximum")
        return self


class Understanding(StrictModel):
    intent: Intent
    filters: Filters = Field(default_factory=Filters)
    positions: list[int] = Field(default_factory=list, max_length=10)
    project: str | None = Field(None, min_length=1, max_length=100)
    campaign_id: UUID | None = None
    missing_information: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def positions_valid(self):
        if len(set(self.positions)) != len(self.positions) or any(type(p) is not int or p < 1 or p > 10 for p in self.positions):
            raise ValueError("invalid_selection")
        if self.intent == "apply" and not self.positions:
            raise ValueError("explicit_selection_required")
        return self


class ToolCall(StrictModel):
    name: ToolName
    arguments: dict = Field(default_factory=dict)


class Plan(StrictModel):
    intent: Intent
    filters: Filters
    selected_jobs: list[UUID] = Field(default_factory=list, max_length=10)
    actions: list[ToolCall] = Field(default_factory=list, max_length=16)
    max_steps: int = Field(16, ge=1, le=16)
    max_tool_calls: int = Field(16, ge=1, le=16)
    max_tokens: int = Field(4000, ge=1, le=4000)
    confirmation_required: bool = True  # Backend output only; never accepted as a model command.
    missing_information: list[str] = Field(default_factory=list, max_length=5)


class Message(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    request_id: UUID = Field(default_factory=uuid4)


class Approval(StrictModel):
    expected_revision: int = Field(ge=1)
    nonce: UUID
    scope: Literal["prepare", "fill", "submit"]
    platforms: list[str] = Field(min_length=1, max_length=8)
    maximum_applications: int = Field(ge=1, le=10)


class Campaign(StrictModel):
    id: UUID
    owner: Literal["primary"] = "primary"
    state: CampaignState = "created"
    revision: int = 1
    plan: Plan
    approval_nonce: UUID = Field(default_factory=uuid4)
    approval: Approval | None = None
    applications: dict = Field(default_factory=dict)
    results: list[dict] = Field(default_factory=list, max_length=100)
    next_step: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    attempts: int = 0
    fence: int = 0
    lease_until: str | None = None
    heartbeat_at: str | None = None
    available_at: str | None = None
    created_at: str
    updated_at: str
