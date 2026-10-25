"""Inspect a disposable AGY home. No credentials copied and no model event sent."""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def main():
    from backend.app.ai.base import ProviderError
    from backend.app.ai.providers.agy import AGENT, bounded_process, portable_schema
    from backend.app.ai.schemas import ModelAnswer

    executable = which("agy")
    if not executable:
        raise SystemExit("cli_unavailable")
    global_settings = Path.home() / ".gemini/antigravity-cli/settings.json"
    before = hashlib.sha256(global_settings.read_bytes()).hexdigest() if global_settings.exists() else None
    evidence = {"verified_at": datetime.now(timezone.utc).isoformat(),
                "model_generation_requested": False, "valid_user_events_sent": 0,
                "credentials_copied": False, "isolated_home": True,
                "useG1Credits": False, "provider_api_credentials_inherited": False}
    with tempfile.TemporaryDirectory(prefix="automated-apply-isolation-") as directory:
        base = Path(directory)
        home, workspace = base / "home", base / "workspace"
        workspace.mkdir()
        for folder in (home / ".gemini/config/agents", workspace / ".agents/agents"):
            folder.mkdir(parents=True)
            (folder / "automated-apply-answer.md").write_text(AGENT)
        config = home / ".gemini/antigravity-cli"
        config.mkdir(parents=True)
        (config / "settings.json").write_text(json.dumps({
            "trustedWorkspaces": [str(workspace)], "agentMode": "plan", "toolPermission": "strict",
            "allowNonWorkspaceAccess": False, "enableTerminalSandbox": True,
            "useG1Credits": False, "hooks": {}, "permissions": {"deny": ["*"]},
        }))
        for path in (home / ".gemini/config/mcp_config.json", config / "mcp_config.json"):
            path.write_text('{"mcpServers":{}}')
        env = {key: value for key, value in os.environ.items() if key in {"PATH", "USER", "TMPDIR", "LANG", "SHELL"}}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), AGY_CLI_DISABLE_AUTO_UPDATE="1")
        for key, args in (("agents", ["agents"]), ("plugins", ["plugin", "list"]), ("mcp", ["mcp", "list"])):
            raw = await bounded_process([executable, *args], "", str(workspace), env, 15)
            output = raw.decode(errors="replace").strip()
            evidence[key + "_isolated"] = (output == "automated-apply-answer" if key == "agents"
                else "No plugins installed" in output if key == "plugins" else "No MCP servers configured" in output)
        schema = base / "answer.schema.json"
        schema.write_text(json.dumps(portable_schema(ModelAnswer.model_json_schema())))
        try:
            await bounded_process([executable, "--agent", "automated-apply-answer", "--sandbox", "--mode", "plan",
                "--disable-slash-commands", "--model", "gemini-3.8-flash-high",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--json-schema", str(schema), "--print-timeout", "10s", "--log-file", str(base / "cli.log")],
                "", str(workspace), env, 15, diagnostics=evidence, require_tool_free_init=True)
        except ProviderError as exc:
            evidence["error_category"] = exc.code
    after = hashlib.sha256(global_settings.read_bytes()).hexdigest() if global_settings.exists() else None
    evidence["global_settings_unchanged"] = before == after
    evidence["tool_free_authenticated_initialization_verified"] = evidence.get("available_tool_count") == 0
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
