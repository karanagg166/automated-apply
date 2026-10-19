"""FastAPI application entry point for Job Pulse Agent."""

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.application_answers import router as application_answers_router
from backend.app.api.v1.applications import router as applications_router
from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.core.security import require_api_token
from backend.app.db.session import close_db_engine, get_db_session, get_engine
from backend.app.integrations.logging import install_oauth_log_filter
from backend.app.mcp.auth import MCPBoundary
from backend.app.mcp.registry import mcp
from backend.app.schemas.credit import CreditBudgetStatus
from backend.app.schemas.job import JobRead
from backend.app.services.credit_manager import (
    CreditBudgetExhaustedError,
    CreditManager,
)

install_oauth_log_filter()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    logger.info(f"Starting Job Pulse Agent API in '{settings.ENVIRONMENT}' mode...")
    # Initialize DB engine connection
    try:
        get_engine()
        logger.info(
            f"Connected to database engine (schema: {settings.DATABASE_SCHEMA})"
        )
    except Exception as e:
        logger.error(f"Failed to initialize database engine during startup: {e}")

    async with mcp_app.lifespan(app):
        yield

    logger.info("Shutting down Job Pulse Agent API...")
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
    response = await call_next(request)
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
        ("/api/v1/startups", "/api/v1/discovery", "/api/v1/jobs", "/api/v1/companies/", "/api/v1/contact-enrichment", "/api/v1/contacts/", "/api/v1/outreach", "/api/v1/integrations", "/api/v1/applications", "/api/v1/application-packets")
    )
    callback = request.url.path == "/api/v1/integrations/gmail/oauth/callback"
    application_request = request.url.path.startswith(
        ("/api/v1/applications", "/api/v1/application-packets")
    ) or "/application-" in request.url.path
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
        async for chunk in request.stream():
            size += len(chunk)
            if size > (65536 if application_request else 1048576):
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Application request exceeds 64 KiB" if application_request else "Discovery request exceeds 1 MiB"},
                    headers={"Cache-Control": "no-store"},
                )
            chunks.append(chunk)
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
        content={"detail": str(exc), "error_type": "invalid_argument"},
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
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "schema": settings.DATABASE_SCHEMA,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Readiness database probe failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


# API v1 Endpoints
@app.get("/api/v1/credits/status", response_model=CreditBudgetStatus, tags=["Credits"])
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


# Exactly one stateless Streamable HTTP endpoint; explicit native host/origin guard.
mcp_app = mcp.http_app(path="/", transport="http", stateless_http=True, json_response=True,
                       host_origin_protection=True, allowed_hosts=settings.MCP_ALLOWED_HOSTS,
                       allowed_origins=settings.MCP_ALLOWED_ORIGINS)
app.mount("/mcp", mcp_app)
app.add_middleware(MCPBoundary)


@app.exception_handler(RequestValidationError)
async def private_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/api/v1/startups", "/api/v1/integrations", "/api/v1/outreach", "/api/v1/applications", "/api/v1/application-packets")) or "/application-" in request.url.path:
        return JSONResponse({"detail": "Invalid request"}, status_code=422,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
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
    return JSONResponse({"detail": "Saved record or candidate profile not found"}, status_code=404,
                        headers={"Cache-Control": "no-store"})


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_token)])
async def saved_job_detail(job_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await SavedDataService(session).job(job_id)


@app.get("/api/v1/jobs/{job_id}/match", dependencies=[Depends(require_api_token)])
async def saved_job_match(job_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await SavedDataService(session).match(job_id)


@app.get("/api/v1/companies/{company_id}/details", dependencies=[Depends(require_api_token)])
async def saved_company_detail(company_id: UUID, session: AsyncSession = Depends(get_db_session)):
    return await SavedDataService(session).company(company_id)


@app.get("/api/v1/companies/{company_id}/recommended-contacts", dependencies=[Depends(require_api_token)])
async def saved_company_contacts(company_id: UUID, limit: int = Query(25, ge=1, le=100),
                                 session: AsyncSession = Depends(get_db_session)):
    return await SavedDataService(session).contacts(company_id, limit)

from backend.app.api.v1.startups import router as startups_router

app.include_router(startups_router)
