"""Gmail is strictly Read + Draft only in the active Python runtime."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend/app"
SEND_MARKERS = ("send_email", "gmail_send", "gmail.send", "send-preview", "send-attempts")
# Legacy send modules were deleted in Phase 2 (owner-approved); they must never return.
FROZEN_SEND_MODULES = {"backend.app.services.gmail_sending", "backend.app.integrations.gmail.send_client"}


def _all_routes(routes, prefix=""):
    """Flatten nested routers (FastAPI >=0.143 wraps include_router in _IncludedRouter)."""
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _all_routes(nested.routes, prefix + (getattr(nested, "prefix", "") or ""))
        else:
            yield prefix + (getattr(route, "path", "") or ""), getattr(route, "name", "") or ""


def test_no_http_route_can_send_email():
    from backend.app.main import app

    routes = list(_all_routes(app.routes))
    assert len(routes) > 100  # guard against silently walking an empty tree
    paths = [*routes, *((path, "") for path in app.openapi()["paths"])]
    for path, name in paths:
        assert not path.endswith("/send"), path
        assert not any(marker in path or marker in name for marker in SEND_MARKERS), path


async def test_no_mcp_tool_or_capability_can_send():
    from backend.app.browser_v2 import browser_mcp
    from backend.app.mcp import permissions, registry

    for server in (registry.mcp, browser_mcp.mcp):
        names = {tool.name for tool in await server.list_tools()}
        assert not any("send" in name or "mail" in name for name in names), names
    assert "send_email" not in {c.value for c in permissions.Capability}
    assert "send_email" not in permissions.allowed_capabilities()
    assert "send_email" not in permissions.TOOL_CAPABILITIES.values()


def test_oauth_never_requests_gmail_send_scope():
    from backend.app.core.config import get_settings
    from backend.app.integrations.google_oauth import GoogleOAuth
    from backend.app.integrations.token_store import ConnectionError

    with pytest.raises(ConnectionError, match="gmail_send_scope_disabled"):
        GoogleOAuth(get_settings()).authorization_url("state", "verifier", None, send=True)


def test_connect_api_rejects_send_authorization_mode():
    from pydantic import ValidationError

    from backend.app.api.v1.integrations import ConnectInput

    with pytest.raises(ValidationError):
        ConnectInput(authorization_mode="send")
    assert ConnectInput(authorization_mode="compose").authorization_mode == "compose"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_deleted_send_modules_stay_deleted():
    for module in FROZEN_SEND_MODULES:
        assert not (ROOT / (module.replace(".", "/") + ".py")).exists(), module


def test_no_active_module_imports_the_frozen_send_code():
    offenders = []
    for path in APP.rglob("*.py"):
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if module in FROZEN_SEND_MODULES:
            continue
        if _imports(path) & FROZEN_SEND_MODULES:
            offenders.append(module)
    assert offenders == []
