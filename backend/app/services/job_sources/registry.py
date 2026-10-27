"""Typed, explicit source identities. Metadata is never evidence of a live connection."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.config import get_settings
from backend.app.schemas.discovery import DiscoveryQuery


class UnknownSourceError(ValueError):
    pass


class SourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    display_name: str
    adapter_type: Literal["direct_api", "apify", "manual", "restricted", "gmail"]
    operations: list[str] = Field(default_factory=lambda: ["jobs"])
    authentication: str = "none"
    availability: Literal[
        "available",
        "configuration_required",
        "authorization_required",
        "manual_import_only",
        "unsupported",
        "temporarily_unavailable",
    ] = "available"
    pricing: Literal["free", "paid", "account_dependent"] = "free"
    enabled: bool = True
    read_only: bool = True
    mutation_capabilities: list[str] = Field(default_factory=list)
    configuration: dict = Field(default_factory=dict)
    live_verified: bool = False


APIFY_PORTALS = (
    "naukri",
    "instahyre",
    "wellfound",
    "work_at_a_startup",
    "cutshort",
    "hirist",
    "foundit",
    "indeed",
    "glassdoor",
)
NAMES = {
    "work_at_a_startup": "YC Work at a Startup",
    "hacker_news": "Hacker News Hiring",
    "gmail_alert": "Gmail job alerts",
}


def source_registry(settings=None):
    settings = settings or get_settings()
    sources = {}
    for name in (
        "greenhouse",
        "lever",
        "ashby",
        "remotive",
        "arbeitnow",
        "hacker_news",
    ):
        boards = getattr(settings, name.upper() + "_BOARDS", None)
        config = (
            {"boards_configured": bool(boards), "board_allowlist_required": True}
            if boards is not None
            else {}
        )
        sources[name] = SourceConfig(
            id=name,
            display_name=NAMES.get(name, name.title()),
            adapter_type="direct_api",
            availability="configuration_required"
            if boards is not None and not boards
            else "available",
            configuration=config,
        )
    for name in APIFY_PORTALS:
        # Validate deployment config without leaking actor inputs, tokens or credentials.
        from backend.app.services.job_sources.apify_adapter import ActorConfiguration

        raw = settings.APIFY_SOURCES.get(name, {})
        try:
            actor = ActorConfiguration.model_validate(raw)
            actor.build_input(DiscoveryQuery())
            configured = (
                actor.enabled
                and actor.reviewed
                and actor.platform_usage_included
                and actor.account_spending_limit_verified
                and bool(settings.APIFY_API_TOKEN)
                and settings.APIFY_PER_RUN_CAP_USD > 0
                and settings.APIFY_MONTHLY_LIMIT_USD >= settings.APIFY_PER_RUN_CAP_USD
            )
        except ValueError:
            configured = False
        sources[name] = SourceConfig(
            id=name,
            display_name=NAMES.get(name, name.title()),
            adapter_type="apify",
            pricing="paid",
            authentication="Apify bearer token and reviewed, permitted actor configuration",
            availability="available" if configured else "configuration_required",
            enabled=configured,
            operations=["jobs", "company_intelligence"]
            if name in ("wellfound", "work_at_a_startup")
            else ["jobs"],
            configuration={"configured": configured, "actor_review_required": True},
        )
    sources["internshala"] = SourceConfig(
        id="internshala",
        display_name="Internshala",
        adapter_type="manual",
        availability="manual_import_only",
        operations=["manual_import"],
    )
    sources["manual"] = SourceConfig(
        id="manual",
        display_name="Manual import",
        adapter_type="manual",
        operations=["manual_import"],
    )
    sources["linkedin"] = SourceConfig(
        id="linkedin",
        display_name="LinkedIn",
        adapter_type="restricted",
        availability="authorization_required",
        authentication="Permitted search provider or user-supplied public URLs",
        operations=["manual_import", "profile_urls_via_public_search"],
        enabled=False,
    )
    sources["apify"] = SourceConfig(
        id="apify",
        display_name="Apify (select a platform)",
        adapter_type="restricted",
        availability="unsupported",
        enabled=False,
    )
    sources["gmail_alert"] = SourceConfig(
        id="gmail_alert",
        display_name="Gmail alerts (legacy parser)",
        adapter_type="gmail",
        pricing="account_dependent",
        availability="manual_import_only",
        authentication="OAuth read-only authorization",
        enabled=False,
        operations=["manual_import"],
    )
    return sources


def resolve_source(name, settings=None):
    name = name.strip().lower()
    try:
        return source_registry(settings)[name]
    except KeyError:
        raise UnknownSourceError(f"Unknown discovery source: {name}") from None
