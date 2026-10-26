"""Authenticated CLI metadata only: /usage is CLI-handled, never a model prompt.

Official contract: https://antigravity.google/docs/cli/headless#unsupported-messages
The owner's generation authorization is deliberately not used by this command.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def parse_metadata(raw):
    from backend.app.ai.base import ProviderError
    try:
        value = json.loads(raw)
        usage = value.get("usage", {})
        if (value.get("status") != "SUCCESS" or value.get("num_turns") != 0
                or not usage or any(count != 0 for count in usage.values())):
            raise ValueError
        rows = []
        for row in value.get("response", "").splitlines():
            if re.fullmatch(r"[A-Za-z0-9 /-]+\t[A-Za-z0-9 -]+\t\d{1,3}%\t[0-9TZ:.-]+", row):
                rows.append(row)
        if not rows:
            raise ValueError
        return {"authenticated_read_verified": True, "envelope_status": "SUCCESS",
                "num_turns": 0, "reported_usage": usage, "sanitized_report": "\n".join(rows)}
    except (ValueError, TypeError, AttributeError):
        raise ProviderError("cli_readiness_metadata_unverified") from None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", default=which("agy"))
    args = parser.parse_args()
    from backend.app.ai.base import ProviderError
    from backend.app.ai.providers.agy import (
        AGENT,
        answer_workspace,
        bounded_process,
        verify_no_overage,
        verify_workspace_authorization,
    )
    evidence = {"evidence_type": "actual_cli_handled_usage_report_no_generation",
                "verified_at": datetime.now(timezone.utc).isoformat(), "model_generation_requested": False}
    try:
        workspace = answer_workspace()
        configuration = json.loads((Path.home() / ".gemini/antigravity-cli/settings.json").read_text())
        # With expansion disabled /usage would be an ordinary model prompt.
        if not isinstance(configuration, dict) or configuration.get("disableSlashCommands", False) is not False:
            raise ProviderError("cli_slash_command_expansion_required")
        profile = Path.home() / ".gemini/config/agents/automated-apply-answer.md"
        if not profile.is_file() or profile.is_symlink() or profile.read_text() != AGENT:
            raise ProviderError("restricted_agent_profile_unavailable")
        verify_workspace_authorization(workspace)
        evidence["billing_guard"] = verify_no_overage()
        env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "SHELL"}}
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
        executable = Path(args.executable or "")
        if not executable.is_absolute() or not executable.is_file():
            raise ProviderError("cli_unavailable")
        with tempfile.TemporaryDirectory(prefix="automated-apply-agy-check-") as directory:
            raw = await bounded_process([str(executable), "--agent", "automated-apply-answer", "--sandbox", "--mode", "plan",
                "--print", "/usage", "--output-format", "json", "--print-timeout", "20s",
                "--log-file", str(Path(directory) / "cli.log")], "", str(workspace), env, 25)
        evidence.update(parse_metadata(raw))
        evidence.update({"trusted_workspace": True, "exit_code": 0})
    except (OSError, ValueError):
        evidence.update({"authenticated_read_verified": False, "error_code": "cli_configuration_unverified"})
    except ProviderError as exc:
        evidence.update({"authenticated_read_verified": False, "error_code": exc.code})
    output = ROOT / "reports/phase1/agy-auth.private.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise SystemExit("unsafe_evidence_path")
    with output.open("w") as target:
        output.chmod(0o600)
        target.write(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    if not evidence.get("authenticated_read_verified"):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
