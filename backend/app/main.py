"""FastAPI application entry point for Job Pulse Agent."""

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.application_answers import router as application_answers_router
from backend.app.api.v1.applications import router as applications_router
from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.core.security import require_api_token
from backend.app.dashboard.router import router as dashboard_router
from backend.app.db.session import (
    close_db_engine,
    get_db_session,
    get_engine,
    get_readiness_engine,
    get_session_factory,
)
from backend.app.integrations.logging import install_oauth_log_filter
from backend.app.mcp.auth import MCPBoundary
from backend.app.mcp.registry import mcp
from backend.app.operations.boundary import transport_error
from backend.app.operations.health import database_connectivity, database_health
from backend.app.operations.readiness import require_safe_startup
from backend.app.resume_sync.router import router as resume_sync_router
from backend.app.schemas.credit import CreditBudgetStatus
from backend.app.schemas.job import JobRead
from backend.app.services.credit_manager import (
    CreditBudgetExhaustedError,
    CreditManager,
)

install_oauth_log_filter()
settings = get_settings()
_readiness_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    logger.info(f"Starting Job Pulse Agent API in '{settings.ENVIRONMENT}' mode...")
    require_safe_startup(settings)
    app.state.database_audit_verified = False
    try:
        await database_health(get_engine(), settings)
        app.state.database_audit_verified = True
        logger.info("Database connectivity and required schema checked")
    except Exception:
        logger.error("Database startup probe failed")
        if settings.ENVIRONMENT != "testing":
            await close_db_engine()
            raise RuntimeError("Database startup probe failed") from None

    gmail_retention = None
    if settings.GMAIL_RETENTION_ENABLED:
        from backend.app.integrations.gmail.retention import retention_loop
        gmail_retention = asyncio.create_task(retention_loop(get_session_factory()))
    project_refresh = None
    if settings.CANDIDATE_PROJECT_CHECKOUTS:
        from backend.app.candidate_context.runtime import refresh_loop

        project_refresh = asyncio.create_task(
            refresh_loop(settings, get_session_factory())
        )
    if settings.ENVIRONMENT == "testing" and settings.BROWSER_MOCK_SUBMISSION_ENABLED:
        from backend.app.browser.submissions import reconcile_expired

        async with get_session_factory()() as session:
            await reconcile_expired(session)
    try:
        async with mcp_app.lifespan(app):
            yield
    finally:
        global _readiness_task
        if _readiness_task is not None and not _readiness_task.done():
            _readiness_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await _readiness_task
        _readiness_task = None
        if gmail_retention is not None:
            gmail_retention.cancel()
            with suppress(asyncio.CancelledError):
                await gmail_retention
        if project_refresh is not None:
            project_refresh.cancel()
            with suppress(asyncio.CancelledError):
                await project_refresh
        logger.info("Shutting down Job Pulse Agent API...")
        from backend.app.browser.runner import browser

        for packet_id in list(browser.sessions):
            try:
                async with asyncio.timeout(5):
                    await browser.close(packet_id)
            except Exception:
                logger.warning("Dedicated browser shutdown interrupted")
        await close_db_engine()


app = FastAPI(
    title="Job Pulse Agent Backend",
    description="AI-powered job discovery, recruiter contact enrichment, and human-in-the-loop outreach engine.",
    version="0.1.0",
    lifespan=lifespan,
)


# Request timing and structured access logging middleware
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    start_time = time.time()
    local_probe = (
        request.url.path in {"/health", "/ready"}
        and request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
    )
    error = (
        None
        if local_probe
        else transport_error(
            settings,
            request.url.scheme,
            request.headers.get("host", ""),
            request.headers.getlist("origin"),
        )
    )
    if error:
        return JSONResponse(
            {"detail": error}, status_code=403, headers={"Cache-Control": "no-store"}
        )
    try:
        async with asyncio.timeout(120):
            response = await call_next(request)
    except TimeoutError:
        return JSONResponse({"detail": "Request timeout"}, status_code=504)
    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"

    # Avoid cluttering logs with frequent /health probes unless in debug
    if request.url.path not in ("/health", "/ready") or settings.DEBUG:
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} ({duration_ms:.1f}ms)"
        )
    return response


@app.middleware("http")
async def private_discovery_boundary(request: Request, call_next):
    private = request.url.path.startswith(
        (
            "/api/v1/browser",
            "/api/v1/local-agent",
            "/api/v1/dashboard",
            "/api/v1/operations",
            "/api/v1/credits",
            "/api/v1/startups",
            "/api/v1/discovery",
            "/api/v1/jobs",
            "/api/v1/companies/",
            "/api/v1/contact-enrichment",
            "/api/v1/contacts/",
            "/api/v1/outreach",
            "/api/v1/integrations",
            "/api/v1/applications",
            "/api/v1/application-packets",
        )
    )
    callback = request.url.path == "/api/v1/integrations/gmail/oauth/callback"
    application_request = (
        request.url.path.startswith(
            ("/api/v1/browser", "/api/v1/applications", "/api/v1/application-packets")
        )
        or "/application-" in request.url.path
    )
    if private and not callback:
        from fastapi import HTTPException

        from backend.app.core.security import require_api_token

        try:
            await require_api_token(request, None)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={**(exc.headers or {}), "Cache-Control": "no-store"},
            )
        size = 0
        chunks = []
        try:
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > (
                        5 * 1024 * 1024
                        if request.url.path == "/api/v1/dashboard/resumes"
                        else 262144
                        if request.url.path == "/api/v1/local-agent/chrome"
                        else 65536
                        if application_request
                        else 1048576
                    ):
                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": "Chrome request exceeds 256 KiB"
                                if request.url.path == "/api/v1/local-agent/chrome"
                                else "Application request exceeds 64 KiB"
                                if application_request
                                else "Discovery request exceeds 1 MiB"
                            },
                            headers={"Cache-Control": "no-store"},
                        )
                    chunks.append(chunk)
        except TimeoutError:
            return JSONResponse(
                {"detail": "Request body timeout"},
                status_code=408,
                headers={"Cache-Control": "no-store"},
            )
        request._body = b"".join(chunks)
    response = await call_next(request)
    if private:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


# Global exception handlers
@app.exception_handler(CreditBudgetExhaustedError)
async def credit_budget_exception_handler(
    request: Request, exc: CreditBudgetExhaustedError
):
    logger.warning(f"Credit budget check failed: {exc}")
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": str(exc), "error_type": "credit_budget_exhausted"},
    )


@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Invalid argument", "error_type": "invalid_argument"},
    )


# Health & Readiness Probes
@app.get("/health", tags=["System"])
async def health_check() -> dict[str, Any]:
    """Liveness probe indicating that the HTTP server is responsive."""
    return {
        "status": "healthy",
        "service": "job-pulse-agent-api",
        "environment": settings.ENVIRONMENT,
        "schema": settings.DATABASE_SCHEMA,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["System"])
async def readiness_check() -> dict[str, Any]:
    """Readiness probe verifying database connectivity."""
    try:
        if settings.ENVIRONMENT != "testing" and not getattr(app.state, "database_audit_verified", False):
            raise RuntimeError("database_startup_audit_required")
        # Concurrent probes share only a currently running DB observation; no
        # success cache can mask an outage. One cancelled HTTP caller must not
        # cancel the bounded observation used by other callers.
        global _readiness_task
        if _readiness_task is None or _readiness_task.done():
            _readiness_task = asyncio.create_task(
                database_connectivity(get_readiness_engine(), settings)
            )
            _readiness_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
        await asyncio.shield(_readiness_task)
        return {
            "status": "ready",
            "database": "connected",
            "schema": settings.DATABASE_SCHEMA,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        from backend.app.db.errors import database_failure_code

        logger.error("Readiness database probe failed; category=%s", database_failure_code(exc))
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": "database_unavailable",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


# API v1 Endpoints
@app.get(
    "/api/v1/credits/status",
    response_model=CreditBudgetStatus,
    tags=["Credits"],
    dependencies=[Depends(require_api_token)],
)
async def get_credits_status(
    session: AsyncSession = Depends(get_db_session),
) -> CreditBudgetStatus:
    """Retrieve remaining credits, monthly allocations, and cooldown status across all providers."""
    manager = CreditManager(session)
    return await manager.get_credit_status()


@app.get(
    "/api/v1/jobs",
    response_model=list[JobRead],
    tags=["Jobs"],
    dependencies=[Depends(require_api_token)],
)
async def list_jobs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[JobRead]:
    """List discovered jobs with optional status filter."""
    from backend.app.services.saved_data import SavedDataService

    return await SavedDataService(session).jobs(limit, offset, status)


from backend.app.api.v1.profile import router as profile_router

app.include_router(profile_router)
app.include_router(dashboard_router)
app.include_router(resume_sync_router)

from backend.app.automation.router import router as automation_router

app.include_router(automation_router)

from backend.app.local_agent.router import router as local_agent_router

app.include_router(local_agent_router)

from backend.app.agent.router import router as agent_command_router

app.include_router(agent_command_router)


# Exactly one stateless Streamable HTTP endpoint; explicit native host/origin guard.
mcp_app = mcp.http_app(
    path="/",
    transport="http",
    stateless_http=True,
    json_response=True,
    host_origin_protection=True,
    allowed_hosts=settings.MCP_ALLOWED_HOSTS,
    allowed_origins=settings.MCP_ALLOWED_ORIGINS,
)
app.mount("/mcp", mcp_app)
app.add_middleware(MCPBoundary)


@app.exception_handler(RequestValidationError)
async def private_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            {"detail": "Invalid request"},
            status_code=422,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    return await request_validation_exception_handler(request, exc)


# Candidate facts and answer drafts share the Phase 1 authentication boundary.
app.include_router(application_answers_router)
app.include_router(applications_router)

from backend.app.api.v1.discovery import router as discovery_router

app.include_router(discovery_router)

from backend.app.api.v1.contact_enrichment import router as contact_enrichment_router

app.include_router(contact_enrichment_router)

from uuid import UUID

from backend.app.api.v1.integrations import router as integrations_router
from backend.app.api.v1.outreach import router as outreach_router
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.services.saved_data import SavedDataService

app.include_router(integrations_router)
app.include_router(outreach_router)


@app.exception_handler(LookupError)
@app.exception_handler(ProfileNotFoundError)
async def missing_saved_record(request: Request, exc: Exception):
    return JSONResponse(
        {"detail": "Saved record or candidate profile not found"},
        status_code=404,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_token)])
async def saved_job_detail(
    job_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).job(job_id)


@app.get("/api/v1/jobs/{job_id}/match", dependencies=[Depends(require_api_token)])
async def saved_job_match(
    job_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).match(job_id)


@app.get(
    "/api/v1/companies/{company_id}/details", dependencies=[Depends(require_api_token)]
)
async def saved_company_detail(
    company_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    return await SavedDataService(session).company(company_id)


@app.get(
    "/api/v1/companies/{company_id}/recommended-contacts",
    dependencies=[Depends(require_api_token)],
)
async def saved_company_contacts(
    company_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    return await SavedDataService(session).contacts(company_id, limit)


from backend.app.api.v1.startups import router as startups_router

app.include_router(startups_router)


@app.get("/api/v1/operations/status", dependencies=[Depends(require_api_token)])
async def operations_status(session: AsyncSession = Depends(get_db_session)):
    from backend.app.operations.diagnostics import operational_status

    return await operational_status(session, get_session_factory(), settings)


from backend.app.browser.router import assistant_router
from backend.app.browser.router import router as browser_router

app.include_router(browser_router)
app.include_router(assistant_router)


from backend.app.api.v1.provider_research import router as provider_research_router

app.include_router(provider_research_router)

from backend.app.execution.router import router as execution_router

app.include_router(execution_router)
