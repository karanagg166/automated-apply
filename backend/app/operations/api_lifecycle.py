"""API-owned bounded tasks and shared Python-writer lifetime."""

import asyncio
from contextlib import asynccontextmanager, suppress

from backend.app.core.logging import logger
from backend.app.local_agent.process_lock import process_lock
from backend.app.operations.readiness import require_safe_startup


@asynccontextmanager
async def application_lifespan(
    app,
    *,
    settings,
    mcp_app,
    get_engine,
    get_session_factory,
    database_health,
    close_db_engine,
    drain_readiness,
):
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
        await drain_readiness()
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


@asynccontextmanager
async def runtime_lifespan(app, **dependencies):
    if dependencies["settings"].ENVIRONMENT == "testing":
        async with application_lifespan(app, **dependencies):
            yield
    else:
        async with (
            process_lock(dependencies["settings"], "api"),
            application_lifespan(app, **dependencies),
        ):
            yield
