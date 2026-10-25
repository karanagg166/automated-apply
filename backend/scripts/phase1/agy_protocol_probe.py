"""Inspect headless initialization without ever sending a user/model event."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def main():
    from backend.app.ai.base import ProviderError
    from backend.app.ai.providers.agy import (
        AGENT,
        answer_workspace,
        bounded_process,
        portable_schema,
        verify_no_overage,
        verify_workspace_authorization,
    )
    from backend.app.ai.schemas import ModelAnswer
    workspace = answer_workspace()
    verify_workspace_authorization(workspace)
    for profile in (Path.home() / ".gemini/config/agents/automated-apply-answer.md",
                    workspace / ".agents/agents/automated-apply-answer.md"):
        if profile.is_symlink() or not profile.is_file() or profile.read_text() != AGENT:
            raise ProviderError("restricted_agent_profile_unavailable")
    evidence = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "evidence_type": "actual_cli_initialization_no_user_event",
        "model": "gemini-3.8-flash-high", "effort": "high",
        "valid_user_events_sent": 0, "model_generation_requested": False,
        "billing_guard": verify_no_overage()}
    env = {key: value for key, value in os.environ.items()
        if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "SHELL"}}
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
    with tempfile.TemporaryDirectory(prefix="automated-apply-agy-protocol-") as directory:
        schema = Path(directory) / "answer.schema.json"
        schema.write_text(json.dumps(portable_schema(ModelAnswer.model_json_schema())))
        try:
            await bounded_process(["/opt/homebrew/bin/agy", "--agent", "automated-apply-answer",
                "--sandbox", "--mode", "plan", "--disable-slash-commands",
                "--model", evidence["model"], "--effort", evidence["effort"],
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--json-schema", str(schema), "--print-timeout", "15s",
                "--log-file", str(Path(directory) / "cli.log")],
                "", str(workspace), env, 20, diagnostics=evidence, require_tool_free_init=True)
            evidence["state"] = "empty_input_session_completed"
        except ProviderError as exc:
            evidence.update(state="generation_disabled", error_category=exc.code)
    evidence["tool_free_initialization_verified"] = evidence.get("available_tool_count") == 0
    path = ROOT / "reports/phase1/agy-protocol.private.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(evidence, file, indent=2)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
