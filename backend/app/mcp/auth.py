"""Native FastMCP bearer validation plus an entire-path ASGI resource boundary."""

import asyncio
import secrets
import weakref

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.mcp.permissions import allowed_capabilities


def authentication_configured(settings):
    token = settings.MCP_API_TOKEN.get_secret_value() if settings.MCP_API_TOKEN else ""
    api = (
        settings.JOB_AGENT_API_TOKEN.get_secret_value()
        if settings.JOB_AGENT_API_TOKEN
        else ""
    )
    return len(token.strip()) >= 32 and token == token.strip() and token != api


_limiters = weakref.WeakKeyDictionary()


def mcp_limiter(limit):
    loop = asyncio.get_running_loop()
    return _limiters.setdefault(loop, {}).setdefault(limit, asyncio.Semaphore(limit))


class OwnerTokenVerifier(TokenVerifier):
    async def verify_token(self, token):
        settings = get_settings()
        if not settings.MCP_REMOTE_ENABLED or not authentication_configured(settings):
            return None
        expected = settings.MCP_API_TOKEN.get_secret_value()
        if not secrets.compare_digest(token.encode(), expected.encode()):
            return None
        return AccessToken(
            token=token,
            client_id="single-owner-development",
            subject="owner",
            scopes=sorted(allowed_capabilities(settings)),
        )


class MCPBoundary:
    """Protect /mcp, all methods and descendants before mount redirects/session handling.

    No trust in forwarded headers: uvicorn must trust only the actual TLS proxy.
    Stateless JSON responses make timeouts finite; no persistent bearer sessions.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] not in {"http", "websocket"} or not (
            path == "/mcp" or path.startswith("/mcp/")
        ):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})

        async def deny(code, reason):
            await JSONResponse(
                {"detail": reason}, code, headers={"Cache-Control": "no-store"}
            )(scope, receive, send)

        settings = get_settings()
        if not settings.MCP_REMOTE_ENABLED:
            return await deny(404, "MCP remote transport disabled")
        if not authentication_configured(settings):
            return await deny(503, "MCP authentication not configured")
        headers = {}
        for key, value in scope.get("headers", []):
            if key in headers and key in {
                b"authorization",
                b"host",
                b"origin",
                b"content-length",
            }:
                return await deny(400, "Ambiguous request headers")
            headers[key] = value
        scheme, _, supplied = headers.get(b"authorization", b"").partition(b" ")
        if (
            scheme.lower() != b"bearer"
            or await OwnerTokenVerifier().verify_token(supplied.decode("latin-1"))
            is None
        ):
            return await deny(401, "Invalid or missing MCP bearer token")
        if settings.MCP_REQUIRE_TLS and scope.get("scheme") != "https":
            return await deny(400, "HTTPS required for MCP")
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store")
                ]
            await send(message)

        limiter = mcp_limiter(settings.MCP_MAX_CONCURRENCY)
        if limiter.locked():
            return await deny(429, "MCP concurrency limit reached")
        try:
            async with asyncio.timeout(settings.MCP_REQUEST_TIMEOUT_SECONDS):
                async with limiter:
                    body = bytearray()
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > settings.MCP_MAX_REQUEST_BYTES:
                            return await deny(413, "MCP request too large")
                        if not message.get("more_body", False):
                            break
                    delivered = False

                    async def buffered_receive():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {
                                "type": "http.request",
                                "body": bytes(body),
                                "more_body": False,
                            }
                        return await receive()

                    guard = HostOriginGuardMiddleware(
                        self.app,
                        allowed_hosts=settings.MCP_ALLOWED_HOSTS,
                        allowed_origins=settings.MCP_ALLOWED_ORIGINS,
                        mode="strict",
                    )
                    await guard(scope, buffered_receive, guarded_send)
        except TimeoutError:
            if not started:
                await deny(504, "MCP request timed out")
