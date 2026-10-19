"""Connector claims distinguish configuration, mocks, manual work and live verification."""

from enum import StrEnum

from backend.app.core.config import get_settings
from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.google_oauth import GoogleOAuth
from backend.app.services.job_sources.registry import source_registry


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    CONFIGURATION = "requires_configuration"
    AUTHORIZATION = "requires_authorization"
    MOCK = "mock_tested_only"
    MANUAL = "manual_only"
    UNSUPPORTED = "unsupported"
    LIVE = "live_verified"


async def connector_registry(session, settings=None):
    settings = settings or get_settings()
    sources = source_registry(settings)
    from backend.app.services.startup_discovery.connectivity import ProviderConnectivity

    startup_status = await ProviderConnectivity(session, None, settings).status()
    output = []
    for platform in (
        "linkedin",
        "naukri",
        "instahyre",
        "work_at_a_startup",
        "wellfound",
        "internshala",
        "greenhouse",
    ):
        source = sources[platform]
        status = (
            CapabilityStatus.MANUAL
            if platform == "internshala"
            else CapabilityStatus.MOCK
            if source.availability == "available"
            else CapabilityStatus.CONFIGURATION
        )
        if platform == "linkedin":
            status = (
                CapabilityStatus.MOCK
                if settings.PEOPLE_SEARCH_ENABLED
                and settings.SERPER_API_KEY
                and settings.PUBLIC_SEARCH_RIGHTS_REVIEWED
                and settings.LINKEDIN_SEARCH_RETENTION_AUTHORIZED
                else CapabilityStatus.CONFIGURATION
            )
        caps = {
            "discover_jobs": status,
            "submit_application": CapabilityStatus.MANUAL,
            "generate_answers": CapabilityStatus.MOCK
            if settings.GEMINI_API_KEY and settings.LLM_MODEL
            else CapabilityStatus.CONFIGURATION,
        }
        if platform in {"work_at_a_startup", "wellfound"}:
            caps["discover_companies"] = CapabilityStatus.MANUAL
        if platform == "linkedin":
            caps["discover_jobs"] = CapabilityStatus.MANUAL
            caps["discover_people"] = status
            caps["send_email"] = CapabilityStatus.UNSUPPORTED
        diagnostic = next(
            (s for s in startup_status["providers"] if s["provider"] == platform), None
        )
        if diagnostic and diagnostic["live_verified"]:
            caps["discover_jobs"] = CapabilityStatus.LIVE
        output.append(
            {
                "platform": platform,
                "capabilities": caps,
                "live_verified": bool(diagnostic and diagnostic["live_verified"]),
                "discovery_connection": diagnostic,
            }
        )
    for name in ("apollo", "signalhire"):
        configured = bool(getattr(settings, name.upper() + "_API_KEY")) and getattr(
            settings, name.upper() + "_ENRICHMENT_ENABLED"
        )
        output.append(
            {
                "platform": name,
                "live_verified": False,
                "capabilities": {
                    "enrich_contacts": CapabilityStatus.MOCK
                    if configured
                    else CapabilityStatus.CONFIGURATION,
                    "discover_people": (
                        CapabilityStatus.MOCK
                        if configured
                        else CapabilityStatus.CONFIGURATION
                    )
                    if name == "apollo"
                    else CapabilityStatus.UNSUPPORTED,
                    "send_email": CapabilityStatus.UNSUPPORTED,
                    "submit_application": CapabilityStatus.UNSUPPORTED,
                },
            }
        )
    gmail = await ConnectionService(session, settings).status()
    connected = gmail["status"] == "connected"
    output.append(
        {
            "platform": "gmail",
            "live_verified": gmail["live_verified"],
            "connection": gmail,
            "capabilities": {
                "connect_account": CapabilityStatus.LIVE
                if connected
                else CapabilityStatus.AUTHORIZATION
                if GoogleOAuth(settings).configured()
                else CapabilityStatus.CONFIGURATION,
                "read_account_identity": CapabilityStatus.LIVE
                if connected
                else CapabilityStatus.AUTHORIZATION,
                "read_job_alerts": CapabilityStatus.UNSUPPORTED,
                "create_email_draft": CapabilityStatus.UNSUPPORTED,
                "prepare_local_draft": CapabilityStatus.AVAILABLE,
                "send_email": CapabilityStatus.AVAILABLE
                if settings.GMAIL_SENDING_ENABLED
                and gmail["send_capability"] == "send_authorized"
                else CapabilityStatus.UNSUPPORTED
                if not settings.GMAIL_SENDING_ENABLED
                else CapabilityStatus.AUTHORIZATION
                if connected
                else CapabilityStatus.CONFIGURATION,
                "send_requires_owner_confirmation": True,
                "submit_application": CapabilityStatus.UNSUPPORTED,
            },
        }
    )
    return {"connectors": output, "startup_discovery": startup_status}
