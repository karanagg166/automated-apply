"""Actual closed edit DTOs and revision archive expression, evaluated without ORM/config imports."""
import argparse
import ast
import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as S
from uuid import UUID

from rust.scripts.packet_contract_corpus import packet_models
from rust.scripts.packet_read_corpus import load_method

ROOT = Path(__file__).resolve().parents[2]


async def archive_cases(scope):
    now = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(_zone): return now

    scope.update(datetime=Clock, timezone=timezone, deepcopy=deepcopy, hashlib=hashlib, json=json)
    path = "backend/app/services/applications/resume_selector.py"
    digest = next(n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "digest")
    exec(compile(ast.Module(body=[digest], type_ignores=[]), path, "exec"), scope)
    project = load_method(scope, "backend/app/repositories/application_packet.py", "ApplicationPacketRepository", "field_read")
    path = "backend/app/repositories/application_packet.py"
    tree = ast.parse((ROOT / path).read_text())
    key = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "revision_archive_key")
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ApplicationPacketRepository")
    advance = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "advance")
    assignment = next(n for n in advance.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "archived")
    material = ast.parse("async def material(self,packet):\n return None\n").body[0]
    material.body = [assignment, ast.Return(ast.Name(id="archived", ctx=ast.Load()))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[key, material], type_ignores=[])), path, "exec"), scope)
    snapshot = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-context-corpus.json").read_text())["outputs"][0]
    field = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-fields-corpus.json").read_text())["outputs"][0]["field"]
    field.update(id="10000000-0000-0000-0000-000000000001", proposed_answer="  Original fact  ")
    cases = []
    for revision, approved, human in [(1, None, None), (2, 2, " Owner fact "), (2147483646, None, ""), (2147483647, 2147483647, None)]:
        raw = dict(id="20000000-0000-0000-0000-000000000001", revision=revision, approved_revision=approved, lifecycle_state="approved_for_manual_handoff" if approved else "created", tracking_state="not_applied", snapshot=deepcopy(snapshot))
        row = {**field, "human_answer": human}

        class Repo:
            async def fields(self, *_args): return [S(**row)]
            field_read = staticmethod(project)

        archived = await scope["material"](Repo(), S(**{**raw, "id": UUID(raw["id"])}))
        value = json.loads(json.dumps({"digest": scope["digest"](archived), **archived}, default=str))
        cases.append(dict(packet=raw, fields=[row], key=scope["revision_archive_key"](UUID(raw["id"]), revision), output=value))
    return dict(now=now.isoformat(), cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = packet_models()
    defaults = dict(refresh=dict(expected_revision=1), questions=dict(expected_revision=1, questions=[dict(question="Email")]), answer=dict(expected_revision=1, answer=" Owner fact "))
    models = dict(refresh="PacketEdit", questions="QuestionsAdd", answer="AnswerEdit")
    cases = []
    for kind, base in defaults.items():
        inputs = [base]
        changes = dict(expected_revision=[None, False, True, 0, 1, 1.0, "1.0", "1_000", 1.5, 2147483646, 2147483647], approved_revision=[1], snapshot=[{}], provenance=[{"source": "human"}])
        changes.update(dict(resume_resource_id=[None, "bad", "{10000000000000000000000000000001}"], refresh_saved_data=[None, True, "yes", " false ", 2]) if kind == "refresh" else dict(questions=[None, [], [dict(question="Email")] * 50, [dict(question="Email")] * 51, [dict(question=" ")], [dict(question="Skills", field_type="multi_select", options=["Rust", "Go"])]] ) if kind == "questions" else dict(answer=[None, True, 1, "", " ", " Owner fact ", "\u001cFact\u001f", "é" * 10000, "x" * 10001]))
        for key, values in changes.items():
            inputs.extend({**base, key: value} for value in values)
        for raw in inputs:
            try:
                result = scope[models[kind]].model_validate(raw)
                output = dict(accepted=True, output=result.model_dump(mode="json"), explicit_resume="resume_resource_id" in result.model_fields_set)
            except ValueError:
                output = dict(accepted=False)
            cases.append(dict(kind=kind, input=raw, **output))
    data = dict(contracts=cases, archive=asyncio.run(archive_cases(scope)))
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-edit-corpus.json"
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded: raise SystemExit("packet_edit_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_packet_edit_contracts:{len(cases)} archive_expressions:{len(data['archive']['cases'])}")


if __name__ == "__main__":
    main()
