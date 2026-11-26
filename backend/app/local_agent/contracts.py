"""Owner connection policy contracts for the kept local-agent dashboard routes."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


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
