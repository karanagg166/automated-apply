"""AST-only public packet contracts; never import services, settings, ORM or owner files."""
import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.ai.schemas import Contract as AnswerContract
from backend.app.ai.schemas import EvidenceReference, Question, WritingStyle
from backend.app.schemas.candidate_profile import CandidateProfileCreate

ROOT = Path(__file__).resolve().parents[2]


def packet_models():
    scope = dict(__name__=__name__, Annotated=Annotated, Literal=Literal, UUID=UUID, datetime=datetime, timezone=timezone, BaseModel=BaseModel, Field=Field, field_validator=field_validator, model_validator=model_validator, AnswerContract=AnswerContract, EvidenceReference=EvidenceReference, Question=Question, WritingStyle=WritingStyle, CandidateProfileCreate=CandidateProfileCreate)
    path = "backend/app/services/job_discovery_matcher.py"
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DiscoveryMatch"]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), scope)
    path = "backend/app/schemas/applications.py"
    tree = ast.parse((ROOT / path).read_text())
    constants = {"Lifecycle", "Tracking", "ReadinessState", "FieldCategory", "FieldType", "ValidationState", "ReviewState", "IdempotencyKey"}
    classes = {"Contract", "PlatformCapability", "Destination", "ResumeOption", "ResumeSelection", "Provenance", "QuestionInput", "PacketField", "PacketSnapshot", "Readiness", "PacketPreview", "PacketRead", "PrepareInput", "CreatePacket", "ApplicationEventRead", "RevisionInput", "PacketEdit", "QuestionsAdd", "AnswerEdit"}
    nodes = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in constants or isinstance(n, ast.ClassDef) and n.name in classes]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), scope)
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("packet_oracle_loaded_runtime")
    return scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = packet_models()
    inputs = {"prepare": [{}, {"questions": []}], "create": [{"idempotency_key": "fictional-packet-01"}]}
    for kind in inputs:
        base = {} if kind == "prepare" else dict(idempotency_key="fictional-packet-01")
        for field, values in dict(resume_resource_id=[None, "bad", "10000000-0000-0000-0000-000000000001", "{10000000000000000000000000000001}"], questions=[None, {}, "question", [], [dict(question="Email")], [dict(question=" ")], [dict(question="Email")] * 50, [dict(question="Email")] * 51], candidate_profile_id=["10000000-0000-0000-0000-000000000001"], snapshot=[{}], approved_revision=[1], idempotency_key=[None, "short", " abcdefgh ", "a" * 100, "a" * 101, "abcdefgh!", "abcdefgh\n", "abcdefgh\u001c"]).items():
            for value in values:
                inputs[kind].append({**base, field: value})
        for field, values in dict(question=[None, True, "", " ", " Email ", "\u001cEmail\u001f", "x" * 2000, "x" * 2001], category=[None, "unknown", "experience", "technical_skills", " unknown ", "personal_details"], field_type=["text", "textarea", "url", "file", "multiple_choice", "yes_no", "multi_select", " text ", "hidden"], required=[None, False, True, 0, 1, "false", "yes", " false ", 2], max_characters=[None, 0, 1, 19, 20, 10000, 10001, 1.0, 1.5, "1_000", "9007199254740993"], max_words=[None, 0, 1, 1500, 1501, "1.0"], constraints=[None, "", " ", " Keep it factual ", "x" * 1000, "x" * 1001], options=[None, [], ["Yes", "No"], [""], [" "], ["A", "a"], ["Straße", "STRASSE"], ["İ", "I\u0307"], ["\u001c", "A"], [1], ["x" * 201], ["A"] * 51], writing_style=[None, "professional", "concise", " concise ", "unknown"], answer=["injected"], provenance=[{"source": "human"}], effective_answer=["injected"], reviewed=[True]).items():
            for value in values:
                question = dict(question="Describe your work", **{field: value}) if field != "question" else dict(question=value)
                inputs[kind].append({**base, "questions": [question]})
        for field_type in ["multiple_choice", "yes_no", "multi_select"]:
            for options in [[], ["Yes", "No"], [" Rust ", "Python"], ["Rust", "RUST"], ["\u001c"], [" "]]:
                inputs[kind].append({**base, "questions": [dict(question="Choose facts", field_type=field_type, options=options)]})
    cases = []
    for kind, values in inputs.items():
        model = scope["PrepareInput" if kind == "prepare" else "CreatePacket"]
        for value in values:
            try:
                result = dict(accepted=True, output=model.model_validate(value).model_dump(mode="json"))
            except ValueError:
                result = dict(accepted=False)
            cases.append(dict(kind=kind, input=value, **result))
    outputs = [(ROOT / "rust/agent-runtime/schemas" / f"packet-{name}.json", scope[model].model_json_schema()) for name, model in [("prepare", "PrepareInput"), ("create", "CreatePacket"), ("snapshot", "PacketSnapshot"), ("field", "PacketField"), ("read", "PacketRead"), ("event", "ApplicationEventRead")]]
    outputs.append((ROOT / "rust/agent-runtime/tests/fixtures/packet-contract-corpus.json", cases))
    for target, value in outputs:
        encoded = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        if check:
            if target.read_text() != encoded:
                raise SystemExit("packet_contract_drift")
        else:
            target.write_text(encoded)
    print(f"fictional_packet_request_contracts:{len(cases)}")


if __name__ == "__main__":
    main()
