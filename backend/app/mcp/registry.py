"""The only MCP instance. Wrappers authorize even direct invocations; business logic stays in services."""

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.server.middleware.authorization import AuthMiddleware
from pydantic import Field

from backend.app.core.config import get_settings
from backend.app.db.session import get_db_context
from backend.app.integrations.registry import connector_registry
from backend.app.mcp.audit import ToolAuditMiddleware, protected
from backend.app.mcp.auth import OwnerTokenVerifier, authentication_configured
from backend.app.mcp.permissions import allowed_capabilities, component_authorized
from backend.app.schemas.outreach import DraftInput
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.services.outreach_drafting import OutreachDraftingService
from backend.app.services.saved_data import SavedDataService

mcp = FastMCP(
    get_settings().FASTMCP_SERVER_NAME,
    auth=OwnerTokenVerifier(),
    middleware=[ToolAuditMiddleware(), AuthMiddleware(auth=component_authorized)],
    mask_error_details=True,
    strict_input_validation=True,
    tasks=False,
)


def mcp_status():
    settings = get_settings()
    configured = authentication_configured(settings)
    return {
        "enabled": settings.MCP_REMOTE_ENABLED,
        "authentication_configured": configured,
        "transport": "streamable-http",
        "authentication_model": "single-user development bearer",
        "available_capability_groups": sorted(allowed_capabilities(settings)),
        "last_validation_status": "configured_not_live_verified"
        if configured
        else "not_configured",
        "session_mode": "stateless",
        "endpoint": "/mcp/",
    }


@mcp.tool()
@protected("read_discovery")
async def list_discovery_sources() -> list[dict]:
    """List source configuration without executing a connector."""
    async with get_db_context() as session:
        return SavedDataService(session).sources()


@mcp.tool()
@protected("read_discovery")
async def search_saved_jobs(
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0, le=100000)] = 0,
    status: str | None = None,
) -> list[dict]:
    """Read saved jobs; no live discovery or database writes."""
    async with get_db_context() as session:
        return await SavedDataService(session).jobs(limit, offset, status)


@mcp.tool()
@protected("read_discovery")
async def get_job_details(job_id: UUID) -> dict:
    """Read a saved job."""
    async with get_db_context() as session:
        return await SavedDataService(session).job(job_id)


@mcp.tool()
@protected("read_profile")
async def match_job_against_saved_profile(job_id: UUID) -> dict:
    """Deterministic match using the persisted primary candidate profile."""
    async with get_db_context() as session:
        return await SavedDataService(session).match(job_id)


@mcp.tool()
@protected("read_profile")
async def get_verified_profile_summary() -> dict:
    """Read confirmed career information from the saved primary profile."""
    async with get_db_context() as session:
        return await CandidateProfileService(session).get_verified_career_information()


@mcp.tool()
@protected("read_discovery")
async def get_company_details(company_id: UUID) -> dict:
    """Read saved employer intelligence; company claims retain source provenance."""
    async with get_db_context() as session:
        return await SavedDataService(session).company(company_id)


@mcp.tool()
@protected("read_contacts")
async def list_recommended_company_contacts(
    company_id: UUID, limit: Annotated[int, Field(ge=1, le=100)] = 25
) -> list[dict]:
    """Read cached, ranked contacts with verification warnings; never enrich."""
    async with get_db_context() as session:
        return await SavedDataService(session).contacts(company_id, limit)


@mcp.tool()
@protected("read_contacts")
async def get_contact_evidence(contact_id: UUID) -> dict:
    """Read contact identity evidence and its freshness/retention status."""
    async with get_db_context() as session:
        return await SavedDataService(session).contact_details(contact_id)


@mcp.tool()
@protected("read_integration_status")
async def get_integration_status() -> dict:
    """Read connection identity/capability status without credentials."""
    async with get_db_context() as session:
        return {**await connector_registry(session), "mcp": mcp_status()}


@mcp.tool()
@protected("prepare_draft")
async def prepare_founder_outreach_draft(
    contact_id: UUID,
    job_id: UUID | None = None,
    idempotency_key: Annotated[
        str, Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ]
    | None = None,
) -> dict:
    """Explicitly persist a local grounded draft. No paid provider, approval, Gmail draft or send."""
    async with get_db_context() as session:
        return await OutreachDraftingService(session).create(
            DraftInput(
                contact_id=contact_id,
                job_id=job_id,
                use_llm=False,
                idempotency_key=idempotency_key,
            ),
            origin="mcp",
        )


@mcp.tool()
@protected("prepare_draft")
async def get_outreach_draft(draft_id: UUID) -> dict:
    """Read a local email draft; requires the explicit draft capability."""
    async with get_db_context() as session:
        return await OutreachDraftingService(session).read(draft_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
