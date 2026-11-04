"""Verify the owner's registered DevTools MCP in its separate headless browser.

No application environment, authenticated Chrome profile, provider URL or queue
mutation is used. Only a new owned about:blank page receives fixture markup.
"""
import asyncio
import json
import os
import plistlib
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

NAME = "chrome-devtools"
PROFILE = Path.home() / "Library/Application Support/Automated Apply/developer-tools/chrome-devtools-mcp/browser-profile"


def browser_state():
    """Read focus and window/tab IDs only; never inspect owner URLs or titles."""
    script = '''ObjC.import('AppKit');
const chrome = Application('Google Chrome');
JSON.stringify({frontmost: $.NSWorkspace.sharedWorkspace.frontmostApplication.bundleIdentifier.js,
chromeRunning:chrome.running(),
windows:chrome.running() ? chrome.windows().map(w => ({id:w.id(),activeTab:w.activeTab().id()})) : []});'''
    result = subprocess.run(["osascript", "-l", "JavaScript", "-e", script],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        return None
    return json.loads(result.stdout)


def content(result):
    value = result.model_dump(mode="json", by_alias=True)
    if value.get("isError", value.get("is_error")):
        raise RuntimeError("devtools_tool_failed")
    return "\n".join(block["text"] for block in value.get("content", [])
                     if block.get("type") == "text")


def page_ids(value):
    return {int(x) for x in re.findall(r"(?m)^\s*(?:[-*]\s*)?(\d+):\s+about:blank", value)}


async def verify():
    config = tomllib.loads((Path.home() / ".codex/config.toml").read_text())["mcp_servers"][NAME]
    args = config["args"]
    if PROFILE.resolve() != PROFILE:
        raise ValueError("personal_profile_alias_not_allowed")
    if ("--headless" not in args or "--userDataDir=" + str(PROFILE) not in args
            or any(a.startswith(("--autoConnect", "--auto-connect", "--browserUrl", "--browser-url",
                                 "--wsEndpoint", "--ws-endpoint")) for a in args)):
        raise ValueError("separate_headless_browser_configuration_required")
    executables = [a.removeprefix("--executablePath=") for a in args
                   if a.startswith("--executablePath=")]
    if len(executables) != 1 or not Path(executables[0]).is_file():
        raise ValueError("explicit_testing_browser_required")
    app = next((p for p in Path(executables[0]).parents if p.suffix == ".app"), None)
    if (app is None or plistlib.loads((app / "Contents/Info.plist").read_bytes())
            .get("CFBundleIdentifier") != "com.google.chrome.for.testing"):
        # A second headless com.google.Chrome process can hijack AppleScript's
        # application-name lookup even with a separate user-data directory.
        raise ValueError("distinct_macos_testing_browser_identity_required")
    before = browser_state()
    params = StdioServerParameters(command=config["command"], args=args,
                                   env={**os.environ, **config.get("env", {})})
    steps = []
    with open(os.devnull, "w") as errors:
        async with stdio_client(params, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=30) as session:
                initialization = (await session.initialize()).model_dump(mode="json", by_alias=True)
                tools = (await session.list_tools()).model_dump(mode="json", by_alias=True)["tools"]
                names = {t["name"] for t in tools}
                required = {"list_pages", "new_page", "evaluate_script", "take_snapshot", "close_page"}
                assert required <= names, "required_devtools_tools_missing"
                steps.append("initialize_and_discover_tools")
                existing = page_ids(content(await session.call_tool("list_pages", {})))
                created = content(await session.call_tool("new_page", {"url": "about:blank", "background": True}))
                new_ids = page_ids(created) - existing
                assert len(new_ids) == 1, "owned_new_page_identity_required"
                page_id = new_ids.pop()
                try:
                    steps.append("create_owned_background_blank_page")
                    probe = content(await session.call_tool("evaluate_script", {
                        "pageId": page_id,
                        "function": """() => {
                            if (location.href !== 'about:blank') throw new Error('owned_blank_page_required');
                            document.title='Automated Apply DevTools verification';
                            document.body.innerHTML='<h1>DevTools connection verified</h1>';
                            return {marker:document.querySelector('h1').textContent,headless:navigator.userAgent.includes('HeadlessChrome')};
                        }""",
                    }))
                    assert "DevTools connection verified" in probe and re.search(r'"headless"\s*:\s*true', probe)
                    steps.append("evaluate_dom_in_actual_headless_chrome")
                    snapshot = content(await session.call_tool("take_snapshot", {"pageId": page_id}))
                    assert "DevTools connection verified" in snapshot
                    steps.append("read_actual_accessibility_snapshot")
                finally:
                    content(await session.call_tool("close_page", {"pageId": page_id}))
                    steps.append("close_only_owned_verification_page")
    after = browser_state()
    return {"at": datetime.now(timezone.utc).isoformat(), "server": NAME,
            "server_info": initialization.get("serverInfo", initialization.get("server_info")),
            "tool_count": len(tools), "checks_passed": len(steps), "checks": steps,
            "personal_chrome_metadata_observed": before is not None and after is not None,
            "personal_chrome_focus_and_active_tabs_equal": before == after if before and after else None,
            "personal_chrome_profile_used": False, "provider_navigations": 0,
            "distinct_macos_browser_identity": True,
            "queue_mutations": 0, "application_acceptance_claimed": False}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), indent=2))
