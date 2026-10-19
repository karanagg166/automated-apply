"""Default-deny capabilities, independent of tool discovery or client input."""

from enum import StrEnum

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from backend.app.core.config import get_settings


class Capability(StrEnum):
    READ_PROFILE = "read_profile"
    READ_DISCOVERY = "read_discovery"
    READ_CONTACTS = "read_contacts"
    READ_INTEGRATION_STATUS = "read_integration_status"
    PREPARE_DRAFT = "prepare_draft"
    MUTATE_JOB_STATE = "mutate_job_state"
    EXECUTE_PAID_PROVIDER = "execute_paid_provider"
    SEND_EMAIL = "send_email"
    SUBMIT_APPLICATION = "submit_application"


READ_CAPABILITIES = {c.value for c in Capability if c.value.startswith("read_")}
TOOL_CAPABILITIES = {
    "list_discovery_sources": "read_discovery",
    "search_saved_jobs": "read_discovery",
    "get_job_details": "read_discovery",
    "match_job_against_saved_profile": "read_profile",
    "get_verified_profile_summary": "read_profile",
    "get_company_details": "read_discovery",
    "list_recommended_company_contacts": "read_contacts",
    "get_contact_evidence": "read_contacts",
    "get_integration_status": "read_integration_status",
    "get_outreach_draft": "prepare_draft",
    "prepare_founder_outreach_draft": "prepare_draft",
}
# Legacy functions remain importable by trusted Python code, never registered with MCP.
LEGACY_CAPABILITIES = {
    "lookup_or_create_company": "mutate_job_state",
    "save_discovered_job": "mutate_job_state",
    "update_job_application_status": "mutate_job_state",
    "ingest_jobs_from_source": "mutate_job_state",
    "fetch_jobs_from_source": "execute_paid_provider",
    "check_job_source_connection": "execute_paid_provider",
    "generate_application_draft": "prepare_draft",
    "generate_company_email_candidates": "read_contacts",
    "get_cached_company_contacts": "read_contacts",
    "check_api_credits_status": "read_integration_status",
    "match_job_against_profile": "read_profile",
}


def allowed_capabilities(settings=None):
    settings = settings or get_settings()
    return READ_CAPABILITIES | (
        {"prepare_draft"} if settings.MCP_ALLOW_DRAFT_CREATION else set()
    )


def authorize(capability):
    token = get_access_token()
    # Native middleware skips stdio auth; local process ownership is the explicit boundary.
    from fastmcp.server.context import _current_transport

    local = _current_transport.get() == "stdio"
    if capability not in allowed_capabilities() or (
        not local and (not token or capability not in token.scopes)
    ):
        raise ToolError("Operation not authorized")
    return token.subject or token.client_id if token else "local-owner"


def component_authorized(context):
    capability = TOOL_CAPABILITIES.get(context.component.name)
    return bool(
        context.token
        and capability in allowed_capabilities()
        and capability in context.token.scopes
    )
