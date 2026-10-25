"""Real local subprocess diagnostics; no AGY requests or model quota consumed."""
import json
import sys

import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.providers.agy import (
    AgyProvider,
    bounded_process,
    parse_output,
    portable_schema,
)
from backend.app.ai.schemas import ModelAnswer
from backend.app.core.config import Settings
from backend.tests.test_phase1_local_agent import model_answer


def test_single_stream_result_uses_terminal_envelope():
    raw = json.dumps({"event": "result", "result": {"status": "SUCCESS", "num_turns": 1,
        "structured_output": model_answer(), "usage": {"input_tokens": 3, "output_tokens": 4}}}).encode()
    assert parse_output(raw).usage.output_tokens == 4


def test_portable_schema_keeps_nested_restrictions_without_refs():
    schema = portable_schema(ModelAnswer.model_json_schema())
    assert "$ref" not in json.dumps(schema) and "$defs" not in json.dumps(schema)
    assert schema["additionalProperties"] is False
    claim = schema["properties"]["claims"]["items"]
    assert claim["required"] == ["text", "source", "quote"]
    assert claim["additionalProperties"] is False
    assert "candidate_evidence" in claim["properties"]["source"]["properties"]["source_type"]["enum"]
    assert schema["properties"]["claims"]["minItems"] == 1
    assert schema["properties"]["answer"]["maxLength"] == 10000
    with pytest.raises(ProviderError, match="unsupported_provider_schema"):
        portable_schema({"$ref": "https://example.org/schema.json"})


@pytest.mark.parametrize("step", [{"step_type": "tool", "tool_name": "execute_sql"}, {"step_type": "agent_response", "subagent_info": {"subagents": ["fictional"]}}])
def test_stream_tool_and_delegation_rejected(step):
    raw = json.dumps({"event": "step_update", "step_update": step}) + "\n" + json.dumps({"event": "result", "result": {"structured_output": model_answer()}})
    with pytest.raises(ProviderError, match="provider_tool_use_denied"):
        parse_output(raw.encode())


@pytest.mark.asyncio
async def test_timeout_preserves_only_safe_progress(tmp_path):
    diagnostics = {}
    code = 'import json,time; print(json.dumps({"event":"init","init":{"tools":[]},"secret":"do-not-store"}),flush=True); time.sleep(5)'  # pragma: allowlist secret -- fictional redaction sentinel
    with pytest.raises(ProviderError, match="timeout"):
        await bounded_process([sys.executable, "-c", code], "", str(tmp_path), {}, .5, diagnostics)
    assert diagnostics == {"last_event": "init", "available_tool_count": 0}
    assert "secret" not in json.dumps(diagnostics)


@pytest.mark.asyncio
async def test_subprocess_tool_availability_fails_closed(tmp_path):
    code = 'import json,sys,pathlib; print(json.dumps({"event":"init","init":{"tools":["run_command"]}}),flush=True); data=sys.stdin.read(); pathlib.Path("received").write_text(data)'
    diagnostics = {}
    with pytest.raises(ProviderError, match="provider_tool_use_denied"):
        await bounded_process([sys.executable, "-c", code], "fictional prompt must not be sent", str(tmp_path), {}, 2, diagnostics, require_tool_free_init=True)
    assert diagnostics["prompt_sent"] is False
    assert not (tmp_path / "received").exists()


@pytest.mark.asyncio
async def test_tool_free_init_precedes_input(tmp_path):
    code = 'import json,sys; print(json.dumps({"event":"init","init":{"tools":[]}}),flush=True); data=sys.stdin.read(); print(json.dumps({"echo":data}),flush=True)'
    diagnostics = {}
    raw = await bounded_process([sys.executable, "-c", code], "fictional", str(tmp_path), {}, 2, diagnostics, require_tool_free_init=True)
    assert diagnostics["prompt_sent"] is True
    assert json.loads(raw.splitlines()[1])["echo"] == "fictional"


@pytest.mark.asyncio
async def test_generation_timeout_has_exactly_one_adapter_attempt():
    calls = []
    async def runner(*args):
        calls.append(args)
        raise ProviderError("timeout")
    settings = Settings(_env_file=None, AGY_ENABLED=True, AGY_QUOTA_AUTHORIZED=True,
        AGY_MODEL="fictional-high", AGY_EXECUTABLE=sys.executable)
    with pytest.raises(ProviderError, match="timeout"):
        await AgyProvider(settings, runner).generate_structured_answer("fictional question", {},
            {"style_instruction": "concise", "max_characters": 50})
    assert len(calls) == 1
