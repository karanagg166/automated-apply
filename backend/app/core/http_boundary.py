"""Pre-parse owner authentication, body bounds and transport policy."""

import asyncio
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.app.core.http_policy import (
    CALLBACKS,
    PRIVATE_PREFIXES,
    application_request,
    maximum_body_bytes,
)
from backend.app.core.logging import logger
from backend.app.operations.boundary import transport_error


async def log_requests_middleware(request: Request, call_next, settings_provider):
    settings = settings_provider()
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


async def private_discovery_boundary(request: Request, call_next):
    private = request.url.path.startswith(PRIVATE_PREFIXES)
    callback = request.url.path in CALLBACKS
    is_application = application_request(request.url.path)
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
                    if size > maximum_body_bytes(request.url.path):
                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": "Chrome request exceeds 256 KiB"
                                if request.url.path == "/api/v1/local-agent/chrome"
                                else "Application request exceeds 64 KiB"
                                if is_application
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


def install_http_boundary(app, settings_provider):
    async def transport(request, call_next):
        return await log_requests_middleware(request, call_next, settings_provider)

    app.middleware("http")(transport)
    app.middleware("http")(private_discovery_boundary)
