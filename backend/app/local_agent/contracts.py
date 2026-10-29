"""Versioned bounded commands; transport establishes the actor, never page data."""
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.browser.contracts import FillReceipt, Inspection
from backend.app.core.urls import PublicHTTPSURL
from backend.app.local_agent.intents import Intent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Operation = Literal[
    "health", "connection_status", "preview_application_url", "preview_job_filters",
    "get_discovery_status", "get_agent_capabilities", "get_application_policy",
    "conversation",
    "observe_platform_session", "inspect_form", "prepare_form_answers", "authorize_form", "record_form_fill",
    "open_application_task", "get_application_task", "update_application_task", "ask_form_questions",
]


class Command(StrictModel):
    version: Literal[1] = 1
    request_id: UUID = Field(default_factory=uuid4)
    command: Operation
    url: PublicHTTPSURL | None = None
    title: str | None = Field(default=None, max_length=250)
    intent: Intent | None = None
    application_id: UUID | None = None
    plan_id: UUID | None = None
    inspection: Inspection | None = None
    field_ids: list[str] = Field(default_factory=list, max_length=24)
    receipt: FillReceipt | None = None
    task_id: UUID | None = None
    expected_task_version: int | None = Field(default=None, ge=1)
    browser_session_id: UUID | None = None
    tab_id: int | None = Field(default=None, ge=0)
    task_event: Literal["bind", "navigation", "refresh", "refreshed", "pause", "paused", "resume", "cancel", "tab_closed", "recover", "recovered", "focus_lost", "active_tab_changed", "network_timeout", "inspection_prepared", "fill_started", "fill_finished", "guard_installed", "guard_released", "worker_restart"] | None = None
    observed_url: str | None = Field(default=None, max_length=2048)
    observation: Literal["signed_in_indicator", "login_required", "unverifiable"] | None = None


class Actor(StrictModel):
    channel: Literal["chrome", "telegram", "owner", "agy"]
    identity: str = Field(min_length=1, max_length=100)


class Result(StrictModel):
    version: Literal[1] = 1
    request_id: UUID
    correlation_id: UUID = Field(default_factory=uuid4)
    ok: bool
    capability: str
    error_code: str | None = None
    data: dict = Field(default_factory=dict)


PLATFORMS = (
    "google_forms", "naukri", "wellfound", "instahyre", "work_at_a_startup",
    "internshala", "employer_forms", "gmail", "linkedin",
)
Policy = Literal["approve", "automatic_preferred", "draft_only", "manual_only", "disabled"]


class PolicyUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    default: Policy = "approve"
    platforms: dict[str, Policy]


def page_kind(url: str) -> str:
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    host = parsed.hostname
    if host == "docs.google.com" and parsed.path.startswith("/forms/"):
        return "google_forms"
    if host == "forms.gle":
        return "google_forms"
    for domain, platform in (
        ("naukri.com", "naukri"), ("wellfound.com", "wellfound"),
        ("instahyre.com", "instahyre"), ("workatastartup.com", "work_at_a_startup"),
        ("internshala.com", "internshala"), ("linkedin.com", "linkedin"),
    ):
        if host == domain or host.endswith("." + domain):
            return platform
    # Classification is a hint from the URL, never evidence that a form was inspected.
    return "employer_forms"
