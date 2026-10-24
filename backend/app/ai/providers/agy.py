"""Tool-free AGY main agent; one bounded call, no fallback or retries.

The installed CLI discovers an explicit tools: [] custom agent. This is the
primary agent, not delegation. Global owner hooks must be reviewed independently;
resume-based generation remains unavailable from Phase 1 commands.
"""
import asyncio
import json
import os
import re
import signal
import tempfile
from pathlib import Path

from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, TokenUsage

AGENT = """---
name: automated-apply-answer
description: Produce one grounded JSON answer without any tools or delegation.
tools: []
mainAgent: true
subagent: false
commandExecutionPolicy: "off"
mcpServers: []
skills: []
plugins: []
---
""" + SYSTEM_INSTRUCTION
MAX_OUTPUT_BYTES = 65536


def verify_no_overage(path=None):
    """Official CLI useG1Credits defaults false; API/Cloud billing is excluded.

    https://antigravity.google/docs/cli/reference/ documents this setting. No
    shared settings are modified, and provider API credentials aren't inherited.
    """
    path = path or Path.home() / ".gemini/antigravity-cli/settings.json"
    try:
        configuration = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ProviderError("quota_billing_configuration_unverified") from None
    if (not isinstance(configuration, dict) or configuration.get("useG1Credits", False) is not False
            or configuration.get("modelProvider") or configuration.get("gcp")
            or configuration.get("customModelsConfig")):
        raise ProviderError("paid_overage_configuration_forbidden")
    return {"useG1Credits": False, "provider_api_or_cloud_billing": False,
            "evidence": "installed_cli_settings_and_official_false_default"}


def answer_workspace():
    return Path.home() / "Library/Application Support/Automated Apply/agy-answer-workspace"


def verify_workspace_authorization(workspace):
    try:
        configuration = json.loads((Path.home() / ".gemini/antigravity-cli/settings.json").read_text())
    except (OSError, ValueError):
        raise ProviderError("owner_workspace_authorization_required") from None
    trusted = configuration.get("trustedWorkspaces", []) if isinstance(configuration, dict) else []
    if not isinstance(trusted, list) or str(workspace) not in trusted:
        raise ProviderError("owner_workspace_authorization_required")


def parse_output(raw, execution_metadata=None):
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ProviderError("provider_output_size")
    try:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            events = [json.loads(line) for line in raw.splitlines() if line.strip()]
            if any(event.get("step_update", {}).get("step_type") in {"tool_call", "tool", "run_command"} for event in events):
                raise ProviderError("provider_tool_use_denied")
            results = [event["result"] for event in events if event.get("event") == "result"]
            if len(results) != 1:
                raise ValueError
            envelope = results[0]
        if not isinstance(envelope, dict):
            raise ValueError
        if envelope.get("status", "SUCCESS") != "SUCCESS" or envelope.get("num_turns", 1) != 1 or envelope.get("is_error") or envelope.get("tool_calls") or envelope.get("permission_denials"):
            raise ProviderError("provider_permission_or_execution_error")
        value = envelope.get("structured_output", envelope.get("response", envelope.get("result", envelope)))
        content = ModelAnswer.model_validate_json(value) if isinstance(value, str) else ModelAnswer.model_validate(value)
        usage_data = envelope.get("usage") or {}
        if execution_metadata is not None:
            execution_metadata.update({"status": envelope.get("status", "SUCCESS"),
                "num_turns": envelope.get("num_turns", 1), "usage": {
                    key: usage_data[key] for key in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens")
                    if isinstance(usage_data.get(key), int) and usage_data[key] >= 0}})
        usage = TokenUsage(input_tokens=usage_data.get("input_tokens"), output_tokens=usage_data.get("output_tokens"))
        return ProviderAnswer(content=content, usage=usage)
    except (ValueError, TypeError, AttributeError, ValidationError):
        raise ProviderError("invalid_structured_response") from None


async def bounded_process(argv, payload, cwd, env, timeout):
    process = None
    try:
        process = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True)
        async def read(stream):
            data = bytearray()
            while chunk := await stream.read(4096):
                data.extend(chunk)
                if len(data) > MAX_OUTPUT_BYTES:
                    raise ProviderError("provider_output_size")
            return bytes(data)
        async with asyncio.timeout(timeout):
            process.stdin.write(payload.encode())
            await process.stdin.drain()
            process.stdin.close()
            stdout, stderr, code = await asyncio.gather(read(process.stdout), read(process.stderr), process.wait())
        if code:
            # Classify without exposing stderr, which may contain prompts/account data.
            lowered = stderr.lower()
            category = "provider_authentication" if b"auth" in lowered or b"login" in lowered else "rate_limited" if b"quota" in lowered or b"429" in lowered else "cli_nonzero_exit"
            raise ProviderError(category)
        return stdout
    except TimeoutError:
        raise ProviderError("timeout") from None
    except OSError:
        raise ProviderError("cli_unavailable") from None
    finally:
        if process is not None:
            # Kill surviving agent-api descendants even if the CLI itself has exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


class AgyProvider:
    def __init__(self, settings, runner=bounded_process):
        self.settings, self.runner = settings, runner
        self.execution_metadata = {}

    async def generate_structured_answer(self, question, grounded_context, instructions):
        settings = self.settings
        if not settings.AGY_ENABLED or not settings.AGY_QUOTA_AUTHORIZED:
            raise ProviderError("provider_execution_not_authorized")
        executable = Path(settings.AGY_EXECUTABLE)
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ProviderError("cli_unavailable")
        if not settings.AGY_MODEL or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", settings.AGY_MODEL):
            raise ProviderError("explicit_model_required")
        payload = build_payload(question, grounded_context, instructions)
        if len(payload) > settings.LLM_MAX_INPUT_CHARS:
            raise ProviderError("input_size_exceeded")
        with tempfile.TemporaryDirectory(prefix="automated-apply-answer-") as directory:
            workspace = Path(directory)
            agent = workspace / ".agents/agents/automated-apply-answer.md"
            agent.parent.mkdir(parents=True)
            agent.write_text(AGENT)
            # No backend/provider credentials are inherited. OAuth stays in CLI-owned storage.
            env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "SHELL"}}
            env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
            if self.runner is bounded_process:
                self.execution_metadata["billing_guard"] = verify_no_overage()
                profile = Path.home() / ".gemini/config/agents/automated-apply-answer.md"
                if (not profile.is_file() or profile.is_symlink() or profile.stat().st_mode & 0o077
                        or profile.read_text() != AGENT):
                    raise ProviderError("restricted_agent_profile_unavailable")
                workspace = answer_workspace()
                if not workspace.is_dir() or workspace.is_symlink() or workspace.stat().st_mode & 0o077:
                    raise ProviderError("owner_workspace_authorization_required")
                template = workspace / ".agents/agents/automated-apply-answer.md"
                if not template.is_file() or template.is_symlink() or template.read_text() != AGENT:
                    raise ProviderError("restricted_agent_profile_unavailable")
                verify_workspace_authorization(workspace)
                # Discovery is local metadata, not an AI request. Fail closed when
                # the installed CLI cannot establish the named tool-free profile.
                discovery = await bounded_process([str(executable), "agents"], "", str(workspace), env, 15)
                if "automated-apply-answer" not in discovery.decode(errors="replace").split():
                    raise ProviderError("restricted_agent_profile_unavailable")
            argv = [str(executable), "--agent", "automated-apply-answer", "--sandbox", "--mode", "plan",
                "--disable-slash-commands", "--model", settings.AGY_MODEL, "--effort", settings.AGY_EFFORT,
                "--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", json.dumps(ModelAnswer.model_json_schema()),
                "--print-timeout", f"{int(settings.AGY_TIMEOUT_SECONDS)}s", "--log-file", str(Path(directory) / "cli.log")]
            wire = json.dumps({"event": "user", "message": {"content": payload}}) + "\n"
            return parse_output(await self.runner(argv, wire, str(workspace), env, settings.AGY_TIMEOUT_SECONDS), self.execution_metadata)
