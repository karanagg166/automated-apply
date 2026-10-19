"""Structured protocol audit, including denied/unknown calls; never log arguments/results."""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from fastmcp.exceptions import AuthorizationError, NotFoundError, ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from backend.app.mcp.permissions import (
    LEGACY_CAPABILITIES,
    TOOL_CAPABILITIES,
    authorize,
)

log = logging.getLogger("job_pulse_agent.mcp.audit")


class ToolAuditMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        started = time.monotonic()
        token = get_access_token()
        from fastmcp.server.context import _current_transport

        actor = (
            (token.subject or token.client_id)
            if token
            else (
                "local-owner"
                if _current_transport.get() == "stdio"
                else "unauthenticated"
            )
        )
        name = context.message.name
        safe_name = (
            name
            if name in TOOL_CAPABILITIES or name in LEGACY_CAPABILITIES
            else "unregistered_tool"
        )
        outcome, category = "error", None
        try:
            result = await call_next(context)
            outcome = "success"
            return result
        except (AuthorizationError, NotFoundError):
            outcome, category = "denied", "not_authorized_or_unregistered"
            raise
        except asyncio.CancelledError:
            outcome, category = "cancelled", "cancelled"
            raise
        except Exception:
            category = "validation_or_execution_error"
            raise
        finally:
            log.info(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tool": safe_name,
                        "outcome": outcome,
                        "request_id": str(uuid.uuid4()),
                        "actor_id": actor,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                        "error_category": category,
                    }
                )
            )


def protected(capability):
    """Independent authorization and sanitized errors even if discovery/middleware is bypassed."""

    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            authorize(capability)
            try:
                return await function(*args, **kwargs)
            except (ValueError, LookupError):
                raise ToolError(
                    "Invalid input, missing record, or review required"
                ) from None
            except Exception:
                raise ToolError(
                    "Tool failed; consult the audit request identifier"
                ) from None

        return wrapped

    return decorate
