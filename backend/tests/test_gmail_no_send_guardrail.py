"""Gmail is strictly Read + Draft only in the active Python runtime."""

import ast
import re
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
    import importlib.util

    from backend.app.browser_v2 import browser_mcp

    # The legacy FastMCP server/registry was retired in Phase 9E and must stay gone.
    assert importlib.util.find_spec("backend.app.mcp") is None
    names = {tool.name for tool in await browser_mcp.mcp.list_tools()}
    assert not any("send" in name or "deliver" in name or "smtp" in name for name in names), names
    mail_tools = {name for name in names if "mail" in name}
    # Phase 5: only the enumerated READ + DRAFT tools may mention mail at all.
    assert mail_tools <= browser_mcp.DRAFT_ONLY_MAIL_TOOLS, mail_tools - browser_mcp.DRAFT_ONLY_MAIL_TOOLS
    assert set(browser_mcp.TOOL_NAMES) == names


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


# --- Phase 5: the mail_v2 draft bridge is READ + DRAFT ONLY (static + runtime) -------------
MAIL_V2 = APP / "mail_v2"
DRAFT_PATH_SOURCES = [*sorted(MAIL_V2.rglob("*.py")), *sorted((APP / "enrichment_v2").rglob("*.py")),
                      APP / "browser_v2/quota.py", APP / "browser_v2/live_smoke.py"]
PY_DELIVERY = re.compile(r"\bsmtplib\b|\bsend_message\b|\bsendmail\b|\.send\(|mail\.send|gmail\.send|"
                         r"\bSMTP(?:_SSL)?\(|gmail\.compose|\bsend_draft\b|drafts\(\)\.send")
SCRIPT_FORBIDDEN = re.compile(r"\bsend\b|activate|\bdelete\b|do shell script", re.IGNORECASE)


def test_mail_v2_package_exists_with_the_expected_modules():
    names = {path.name for path in MAIL_V2.iterdir()}
    assert {"imap_drafts.py", "mail_app_drafts.py", "mail_app_drafts.js", "composer.py", "service.py"} <= names


@pytest.mark.parametrize("path", DRAFT_PATH_SOURCES, ids=lambda p: str(p.relative_to(APP)))
def test_draft_path_python_has_no_delivery_code(path):
    text = path.read_text()
    assert not PY_DELIVERY.search(text), (path, PY_DELIVERY.search(text).group(0))
    assert "smtplib" not in _imports(path) and "email.mime" not in " ".join(_imports(path))
    assert "activate" not in text.lower().replace("deactivate", "")


def test_mail_app_script_never_sends_activates_or_shells_out():
    script = (MAIL_V2 / "mail_app_drafts.js").read_text()
    assert not SCRIPT_FORBIDDEN.search(script), SCRIPT_FORBIDDEN.search(script).group(0)
    assert "visible: false" in script and "mail.save(draft)" in script
    assert "osascript -e" not in (MAIL_V2 / "mail_app_drafts.py").read_text()


def test_imap_client_only_appends_to_drafts_with_the_draft_flag():
    source = (MAIL_V2 / "imap_drafts.py").read_text()
    calls = set(re.findall(r"imap\.(\w+)\(", source))
    assert calls <= {"login", "logout", "list", "append", "select", "fetch"}, calls
    assert r"(\Draft)" in source and "readonly=True" in source
    assert not re.search(r"imap\.(?:store|expunge|copy|move|uid)\(", source)


async def test_mail_draft_service_runtime_surface_has_no_delivery_method():
    from backend.app.browser_v2.store import MemoryStore
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.imap_drafts import ImapDraftClient
    from backend.app.mail_v2.mail_app_drafts import MailAppDraftClient
    from backend.app.mail_v2.service import MailDraftService

    service = MailDraftService(MemoryStore(), MailConfig())
    for obj in (service, ImapDraftClient(MailConfig()), MailAppDraftClient(MailConfig())):
        public = [name for name in dir(obj) if not name.startswith("_")]
        assert not [name for name in public if "send" in name or "deliver" in name or "smtp" in name], public
    assert service.status()["permission"] == "READ_AND_DRAFT_ONLY"


def test_mail_app_runner_rejects_any_action_but_draft_and_probe():
    script = (MAIL_V2 / "mail_app_drafts.js").read_text()
    assert 'request.action !== "draft"' in script and 'throw Error("operation_denied")' in script


# --- Phase 6A: read-only inbox reader, control agent, event bus, auto-login, 9 new adapters -----------
# The read-only reader: the reader.py facade plus the modules it was split into (Phase 9A).
READER_SOURCES = [*sorted((APP / "mail_v2").glob("read*.py")),
                  *(APP / "mail_v2" / name for name in ("imap_reader.py", "gmail_api_reader.py",
                                                         "mail_app_reader.py", "event_store.py"))]
PHASE6A_SOURCES = [*sorted((APP / "agent_v2").rglob("*.py")), *sorted((APP / "events_v2").rglob("*.py")),
                   *READER_SOURCES, APP / "browser_v2/auth.py", APP / "browser_v2/digest.py",
                   APP / "browser_v2/resume.py", APP / "browser_v2/receipts.py",
                   *sorted(p for p in (APP / "browser_v2/adapters").rglob("*.py") if "__pycache__" not in p.parts)]


def test_phase6a_packages_exist():
    for path in PHASE6A_SOURCES:
        assert path.exists(), path
    assert (MAIL_V2 / "mail_app_reader.js").exists()


@pytest.mark.parametrize("path", PHASE6A_SOURCES, ids=lambda p: str(p.relative_to(APP)))
def test_phase6a_python_has_no_email_delivery_code(path):
    text = path.read_text()
    assert not PY_DELIVERY.search(text), (path, PY_DELIVERY.search(text).group(0))
    imports = _imports(path)
    assert "smtplib" not in imports and not any(i.startswith("email.mime") for i in imports)
    assert not (imports & FROZEN_SEND_MODULES)


def test_mail_reader_imap_is_examine_and_peek_only():
    assert MAIL_V2 / "reader.py" in READER_SOURCES and MAIL_V2 / "imap_reader.py" in READER_SOURCES
    source = "\n".join(path.read_text() for path in READER_SOURCES)
    calls = set(re.findall(r"imap\.(\w+)\(", source))
    assert {"login", "select", "search", "fetch"} <= calls, calls
    assert calls <= {"login", "logout", "select", "search", "fetch"}, calls
    assert "readonly=True" in source and "BODY.PEEK[]" in source
    assert not re.search(r"imap\.(?:store|expunge|copy|move|append|uid)\(", source)  # no flag writes at all


def test_mail_app_reader_script_is_read_only():
    script = (MAIL_V2 / "mail_app_reader.js").read_text()
    assert not SCRIPT_FORBIDDEN.search(script), SCRIPT_FORBIDDEN.search(script).group(0)
    for forbidden in ("OutgoingMessage", "outgoingMessages", "mail.save", "readStatus", ".move(", "mail.move",
                      ".delete("):
        assert forbidden not in script, forbidden
    assert 'request.action !== "read_recent"' in script and 'throw Error("operation_denied")' in script


async def test_mail_read_service_runtime_surface_is_read_only():
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.reader import (
        GmailApiReadClient,
        ImapReadClient,
        MailAppReadClient,
        MailReadService,
    )

    service = MailReadService(MailConfig())
    for obj in (service, ImapReadClient(MailConfig()), GmailApiReadClient(), MailAppReadClient(MailConfig())):
        public = [name for name in dir(obj) if not name.startswith("_")]
        assert not [n for n in public if any(w in n for w in ("send", "deliver", "smtp", "draft", "append",
                                                                "delete", "move", "flag"))], public
    assert service.status()["permission"] == "READ_ONLY"


async def test_control_agent_has_no_send_tool_and_refuses_email_sending():
    from backend.app.agent_v2.control_graph import ALLOWED_TOOLS, ControlAgent
    from backend.app.agent_v2.tools import AgentTools
    from backend.app.browser_v2.store import MemoryStore

    assert not [t for t in ALLOWED_TOOLS if any(w in t for w in ("send", "mail", "deliver", "delete"))]
    assert not [n for n in dir(AgentTools) if any(w in n for w in ("send", "deliver", "delete", "replay"))]
    agent = ControlAgent(MemoryStore())
    for text in ("send the draft to the recruiter", "email the recruiter at Acme now", "send all drafts"):
        result = await agent.run(text)
        assert result["tool"] == "forbidden" and result["verdict"] == "rejected" and not result["ok"], text


async def test_mcp_phase6a_tools_are_read_or_guardrailed_only():
    from backend.app.browser_v2 import browser_mcp

    names = {tool.name for tool in await browser_mcp.mcp.list_tools()}
    assert {"agent_control_chat", "get_event_bus_status", "list_recruiter_replies"} <= names
    assert not any("send" in n or "deliver" in n or "smtp" in n for n in names)
