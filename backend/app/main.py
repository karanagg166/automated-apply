"""FastAPI application entry point for Job Pulse Agent."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.api.composition import install_routes
from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.db.session import (
    close_db_engine,
    get_engine,
    get_readiness_engine,
    get_session_factory,
)
from backend.app.integrations.logging import install_oauth_log_filter
from backend.app.operations.api_lifecycle import runtime_lifespan
from backend.app.operations.health import database_connectivity, database_health

install_oauth_log_filter()
settings = get_settings()
_readiness_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with runtime_lifespan(
        app,
        settings=settings,
        get_engine=get_engine,
        get_session_factory=get_session_factory,
        database_health=database_health,
        close_db_engine=close_db_engine,
        drain_readiness=drain_readiness,
    ):
        yield


async def drain_readiness():
    global _readiness_task
    if _readiness_task is not None and not _readiness_task.done():
        _readiness_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await _readiness_task
    _readiness_task = None


app = FastAPI(
    title="Job Pulse Agent Backend",
    description="AI-powered job discovery, recruiter contact enrichment, and human-in-the-loop outreach engine.",
    version="0.1.0",
    lifespan=lifespan,
)


from backend.app.core.http_boundary import install_http_boundary
from backend.app.core.http_errors import install_exception_handlers

install_http_boundary(app, lambda: settings)
install_exception_handlers(app)
install_routes(app)


# Global exception handlers


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
        if settings.ENVIRONMENT != "testing" and not getattr(
            app.state, "database_audit_verified", False
        ):
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

        logger.error(
            "Readiness database probe failed; category=%s", database_failure_code(exc)
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": "database_unavailable",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


from backend.app.core.timing import RequestTimingMiddleware

app.add_middleware(RequestTimingMiddleware)
