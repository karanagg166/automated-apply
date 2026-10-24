"""Use installed Codex app-server protocol, without starting an AI turn.

Only tools/list and fixed read-only project metadata calls. OAuth stays in Codex.
"""
import json
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NAME = "supabase-automated-apply"


def main():
    process = subprocess.Popen(["codex", "app-server", "--stdio"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    inbox = queue.Queue()
    def reader():
        for line in process.stdout:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
    threading.Thread(target=reader, daemon=True).start()
    count = 0
    def request(method, params):
        nonlocal count
        count += 1
        process.stdin.write(json.dumps({"id": count, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            message = inbox.get(timeout=max(.1, deadline-time.monotonic()))
            if message.get("id") == count:
                if "error" in message:
                    raise RuntimeError("mcp_protocol_or_authorization_error")
                return message.get("result", {})
        raise RuntimeError("mcp_verification_timeout")
    output = {"connection_name": NAME, "client": "codex", "evidence_type": "actual_cli_mcp_discovery", "generation_requests": 0, "verified_at": datetime.now(timezone.utc).isoformat()}
    configurations = {}
    project_config = ROOT / ".mcp.json"
    if project_config.is_file():
        configurations["claude"] = {"configured": NAME in json.loads(project_config.read_text()).get("mcpServers", {})}
    try:
        listed = subprocess.run(["agy", "mcp", "list"], capture_output=True, text=True, timeout=10, check=True)
        line = next((line for line in listed.stdout.splitlines() if line.split() and line.split()[0] == NAME), "")
        configurations["agy"] = {"configured": bool(line), "disabled": "disabled" in line}
    except (OSError, subprocess.SubprocessError):
        pass
    output["client_configurations"] = configurations
    try:
        request("initialize", {"clientInfo": {"name": "automated-apply-preflight", "version": "1.0"}, "capabilities": {"experimentalApi": True}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        status = request("mcpServerStatus/list", {"serverName": NAME, "detail": "toolsAndAuthOnly"})
        servers = status.get("data", [])
        output["servers"] = [{"name": row.get("name"), "auth_status": row.get("authStatus"), "tools": sorted(row.get("tools", {}))} for row in servers]
        available = {tool for row in servers for tool in row.get("tools", {})}
        thread = request("thread/start", {"cwd": str(ROOT), "approvalPolicy": "never", "sandbox": "read-only"})
        thread_id = thread["thread"]["id"]
        output["read_only_results"] = {}
        for tool, arguments in (("get_project", {"id": "luvdmwnlwaqgvfwlmlom"}), ("get_project_url", {}), ("list_tables", {"schemas": ["public"]}), ("list_extensions", {}), ("list_migrations", {})):
            if tool not in available:
                continue
            result = request("mcpServer/tool/call", {"threadId": thread_id, "server": NAME, "tool": tool, "arguments": arguments})
            if result.get("isError"):
                raise RuntimeError("mcp_read_only_operation_failed")
            # Metadata only, but error messages are still omitted from reports.
            output["read_only_results"][tool] = result
        serialized = json.dumps(output["read_only_results"])
        output["project_url_observed"] = "https://luvdmwnlwaqgvfwlmlom.supabase.co" in serialized
        required = {"get_project_url", "list_tables", "list_migrations"}
        if not required.issubset(output["read_only_results"]) or not output["project_url_observed"]:
            raise RuntimeError("mcp_project_capability_unverified")
        tables = json.loads(output["read_only_results"]["list_tables"]["content"][0]["text"])
        migrations = json.loads(output["read_only_results"]["list_migrations"]["content"][0]["text"])
        output["public_table_count"] = len(tables["tables"])
        output["migration_count"] = len(migrations["migrations"])
        output["state"] = "read_only_results_received"
    except Exception:
        output["state"] = "owner_authorization_required"
        output["blocker"] = "project_read_only_tool_call_not_verified"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    path = ROOT / "reports/phase1/mcp.private.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    path.chmod(0o600)
    # Never print arbitrary server-returned messages or credentials.
    print(json.dumps({key: value for key, value in output.items() if key != "read_only_results"}, indent=2))


if __name__ == "__main__":
    main()
