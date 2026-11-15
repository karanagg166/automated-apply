"""Actual legacy field builder with a fictional injected answer service; no runtime imports."""
import argparse
import ast
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as S
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from backend.app.ai.schemas import (
    AnswerGenerationResult,
    EvidenceReference,
    GenerateRequest,
)
from backend.app.core.urls import PublicHTTPSURL
from rust.scripts.packet_contract_corpus import packet_models
from rust.scripts.question_corpus import classifier_oracle

ROOT = Path(__file__).resolve().parents[2]


def oracle():
    scope = packet_models()
    scope.update(classifier_oracle()[0])
    scope.update(re=re, json=json, hashlib=hashlib, UUID=UUID, uuid4=lambda: UUID(int=42), GenerateRequest=GenerateRequest, EvidenceReference=EvidenceReference, TypeAdapter=TypeAdapter, ValidationError=ValidationError, PublicHTTPSURL=PublicHTTPSURL)

    class StripKnownImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module != "backend.app.services.applications.multi_select":
                raise ValueError("unexpected_field_oracle_import")
            return None

    def load(path, names):
        tree = ast.parse((ROOT / path).read_text())
        nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names or isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
        module = StripKnownImports().visit(ast.Module(body=nodes, type_ignores=[]))
        exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)

    prefix = "backend/app/services/applications/"
    load(prefix + "platforms/base.py", {"safe_url"})
    load(prefix + "resume_selector.py", {"digest", "private_resume_id", "select_resume"})
    load(prefix + "multi_select.py", {"decode", "encode", "verified_choices"})
    load(prefix + "answer_builder.py", {"CATEGORIES", "FACT_CATEGORIES", "value_error", "AnswerBuilder"})
    return scope


async def build(generate=False, rewrite=False):
    scope = oracle()
    profiles = [None, dict(id="10000000-0000-0000-0000-000000000001", verified_skills=["Rust", "Python", "Straße"]), dict(id="10000000-0000-0000-0000-000000000002", verified_skills=[])]
    resource = dict(id="20000000-0000-0000-0000-000000000001", resource_type="resume", label="Fictional resume", url="https://example.com/resume.pdf", source_type="user", user_confirmed=True, is_primary=True, updated_at="2026-11-15T00:00:00.000007+00:00")
    resources = [[], [resource], [{**resource, "user_confirmed": False}], [{**resource, "source_type": "private_upload", "url": "private-resume:30000000-0000-0000-0000-000000000001"}]]
    questions = [dict(question=q) for q in ["Full name", "Email", "Phone number", "GitHub profile URL", "LinkedIn profile URL", "Portfolio URL", "Upload resume", "Resume URL", "Notice period", "Current salary", "What is your work authorization?", "Unknown value", "Describe a project", "experience with Rust", "Introduce yourself", "Why this company?"]]
    questions.extend(dict(question=q, field_type=t, options=options, required=required, max_characters=limit) for q,t,options,required,limit in [
        ("Email","url",[],True,1500),("Email","text",[],True,1),("Email 4 characters","text",[],True,1500),("Email 1 word","text",[],True,1500),("Email","multiple_choice",["Yes","No"],True,1500),("Skills","multi_select",["Rust","Python","Java"],True,1500),("Technical skills (select all that apply)","multi_select",["Python","Rust"],True,1500),("Programming languages","multi_select",["Straße","Java"],False,1500),("Technical skills","multi_select",["Rust","Python"],True,2),("Have you worked 5 years with Rust?","multi_select",["Rust","Python"],True,1500),("Upload resume","multi_select",["Rust"],True,1500),("Resume URL","url",[],True,1500),("Resume URL","text",[],True,1),("Email","file",[],True,1500)])
    questions = [scope["QuestionInput"].model_validate(q).model_dump(mode="json") for q in questions]
    if generate:
        questions.extend(scope["QuestionInput"].model_validate(q).model_dump(mode="json") for q in [dict(question="Describe a project",constraints="Use only confirmed facts",max_characters=10),dict(question="Describe a project"+"x"*1970,constraints="Use confirmed facts"),dict(question="Email",constraints="Keep factual",max_characters=1)])
    results = [dict(question_type="personal_details",status="draft_ready",answer="Fictional Person",source="candidate_profile",requires_review=False), dict(question_type="profile_link",status="draft_ready",answer="https://example.com/profile",source="candidate_resource",requires_review=False), dict(question_type="unknown",missing_information=["Provide a verified fact"]), dict(question_type="profile_link",status="draft_ready",answer="https://example.com/unconfirmed",source="environment_default"), dict(question_type="unknown",status="validation_failed",error_code="fictional_validation_error"), dict(question_type="unknown",status="draft_ready",answer="Yes",source="owner_approved_exact_context",draft_id="40000000-0000-0000-0000-000000000001",missing_input_id="a"*32), dict(question_type="unknown",status="draft_ready",answer=" ",source="candidate_profile"), dict(question_type="unknown",status="draft_ready",answer="Fictional",source="unknown_source",used_llm=True,provider="cohere",model="fictional-model"), dict(question_type="unknown",status="draft_ready",answer="Fictional",used_llm=True,provider="unrecognized_provider")]
    results = [AnswerGenerationResult.model_validate(r).model_dump(mode="json") for r in results]
    outputs, unique, cases = [], {}, []

    class Answers:
        def __init__(self, result):
            self.result, self.request = result, None

        async def generate(self, request):
            self.request = request.model_dump(mode="json")
            return AnswerGenerationResult.model_validate(self.result)

    job = UUID("50000000-0000-0000-0000-000000000001")
    for p, raw_profile in enumerate(profiles):
        profile = S(**{**raw_profile, "id": UUID(raw_profile["id"])}) if raw_profile else None
        for r, inventory in enumerate(resources):
            native = [S(**{**item, "id": UUID(item["id"]), "updated_at": datetime.fromisoformat(item["updated_at"])}) for item in inventory]
            resume = scope["select_resume"](native)
            for q, question in enumerate(questions):
                for a, answer in enumerate(results):
                    answers = Answers(answer)
                    origin = "packet_core" if q < 7 else "user_provided"
                    try:
                        field = await scope["AnswerBuilder"](answers).build(scope["QuestionInput"].model_validate(question), job, profile, origin=origin, resume=resume,generate=generate,rewrite=rewrite)
                        field = field.model_dump(mode="json")
                        field.pop("id")
                        output = dict(accepted=True, field=field, resolution=answers.request)
                    except ValueError:
                        output = dict(accepted=False, resolution=answers.request)
                    key = json.dumps(output, sort_keys=True)
                    if key not in unique:
                        unique[key] = len(outputs)
                        outputs.append(output)
                    cases.append([p,r,q,a,unique[key]])
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("field_oracle_loaded_runtime")
    return dict(profiles=profiles, resources=resources, questions=questions, answers=results, job_id=str(job), outputs=outputs, cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    corpus = asyncio.run(build())
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-fields-corpus.json"
    encoded = json.dumps(corpus, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("packet_fields_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_packet_fields:{len(corpus['cases'])} unique_outputs:{len(corpus['outputs'])}")


if __name__ == "__main__":
    main()
