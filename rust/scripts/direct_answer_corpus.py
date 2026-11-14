"""Original service's pure direct-answer branches against fictional data; no runtime imports."""
import argparse
import ast
import copy
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from backend.app.ai.schemas import (
    AnswerGenerationResult,
    EvidenceReference,
    GenerateRequest,
)
from backend.app.core.text import normalize, phrase_in
from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.schemas.candidate_resources import ResolvedLink
from rust.scripts.question_corpus import classifier_oracle, constants
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def oracle():
    scope, _ = classifier_oracle()
    scope.update(TypeAdapter=TypeAdapter, ValidationError=ValidationError,
                 PublicHTTPSURL=PublicHTTPSURL, ResolvedLink=ResolvedLink, Settings=object,
                 STANDARD_FIELDS={"github": "github_url", "linkedin": "linkedin_url", "portfolio": "portfolio_url"},
                 re=re, normalize=normalize, phrase_in=phrase_in, Decimal=Decimal, dataclass=dataclass,
                 AnswerGenerationResult=AnswerGenerationResult, EvidenceReference=EvidenceReference)
    constants("backend/app/services/profile_link_resolver.py", {"ALIASES", "ENV_FIELDS"}, scope)
    extract("backend/app/services/profile_link_resolver.py", ["ProfileLinkResolver", "resource_types", "is_file_upload"], scope)
    extract("backend/app/knowledge/facts.py", ["FactAnswer", "number", "resolve_fact"], scope)
    path = "backend/app/services/application_answer_service.py"
    tree = ast.parse((ROOT / path).read_text())
    service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ApplicationAnswerService")
    generate = next(n for n in service.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "generate")
    start = next(i for i, n in enumerate(generate.body) if isinstance(n, ast.Assign)
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "classification")
    selected = []
    found = False
    for node in generate.body[start:]:
        node = copy.deepcopy(node)
        if isinstance(node, ast.ImportFrom):
            if node.module != "backend.app.knowledge.facts":
                raise ValueError("unexpected_direct_oracle_import")
            continue
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "resources":
            if not isinstance(node.value, ast.Await):
                raise ValueError("unexpected_resource_read")
            continue
        if isinstance(node, ast.If) and ast.unparse(node.test) == "factual.handled":
            current = node
            while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
                current = current.orelse[0]
            current.orelse = [ast.Return(value=ast.Constant(None))]
            selected.append(node)
            found = True
            continue
        if found:
            # Only the existing final output-bound check belongs to the pure branch oracle.
            if not isinstance(node, ast.If) or not ast.unparse(node.test).startswith("result.answer is not None and"):
                raise ValueError("direct_oracle_length_check_changed")
            selected.append(node)
            break
        selected.append(node)
    assert found
    selected.append(ast.Return(value=ast.Call(func=ast.Attribute(value=ast.Name(id="result", ctx=ast.Load()), attr="model_dump", ctx=ast.Load()), args=[], keywords=[ast.keyword(arg="mode", value=ast.Constant("json"))])))
    function = ast.FunctionDef(name="direct", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=n) for n in ["self", "profile", "resources", "request"]], kwonlyargs=[], kw_defaults=[], defaults=[]), body=selected, decorator_list=[], type_params=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), path, "exec"), scope)
    return scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    scope = oracle()
    base = {"full_name": "Fictional Person", "email": "fictional@example.com"}
    facts = {**base, "phone": "fictional-phone", "verified_skills": ["Rust", "Python"],
             "verified_experience_years": 0, "github_url": "https://github.com/fictional",
             "education": [{"qualification": "Fictional degree", "institution": "Fictional Institute"}],
             "certifications": [{"name": "Fictional credential", "issuer": "Fictional issuer"}],
             "preferences": {"notice_period_days": 0, "remote_preference": "remote", "minimum_salary": 1234567.89,
                             "salary_currency": "INR", "work_authorization": "Only a generic saved string",
                             "current_compensation": {"amount": "1250000.00", "currency": "INR", "period": "year", "kind": "ctc"},
                             "open_to_relocation": False, "current_location": "Fictional City"}}
    raw = [base, facts, {**facts, "verified_skills": [], "education": [], "certifications": [], "phone": None},
           {**facts, "preferences": {"minimum_salary": 1000000}},
           {**facts, "preferences": {"notice_period_days": 3650, "remote_preference": "any"}}]
    raw += [{**facts, "verified_experience_years": n} for n in [0.000001, 0.0001, 1.23456789, 99.999999, 100]]
    profiles = [{**CandidateProfileCreate.model_validate(p).model_dump(mode="json"), "id": "00000000-0000-0000-0000-000000000002", "version": 4} for p in raw]
    profiles.append({**profiles[0], "version": 1})
    resource = {"id": "10000000-0000-0000-0000-000000000001", "resource_type": "resume", "label": "Fictional resume", "url": "private-resume:20000000-0000-0000-0000-000000000001", "user_confirmed": True, "is_primary": True, "source_type": "private_upload", "updated_at": "2026-11-14T00:00:00Z"}
    groups = [[], [resource], [{**resource, "resource_type": "other", "label": "Labs reference", "url": "https://example.com/reference"}]]
    questions = ["Email", "Phone number", "Full name", "Years of professional experience", "Notice period", "Verified skills", "Education", "Certifications", "Remote work preference", "Minimum salary", "Current CTC", "Current CTC in LPA", "Current location", "Are you willing to relocate?", "Are you authorized to work in India?", "What is your work authorization?", "Your authorization status?", "Will you require sponsorship?", "GitHub URL", "Portfolio", "Resume link", "Upload resume", "Labs reference", "Email and phone", "Describe a project you built", "Introduce yourself", "Why this company?", "???", "Email within 2 characters", "Email within ٢ characters", "Full name within 0 words", "Full name within 1 word", "Full name within 999999999999999999999999999999999 words", "Full name within ٢ words", "Notice period within 0 characters", "Describe your salary", "Describe your skills"]
    requests = [GenerateRequest(question=q, writing_style=style, max_characters=maximum, max_words=words)
                for q in questions for style, maximum, words in [("professional", 1500, None), ("concise", 20, 1)]]
    cases = []
    defaults = {"github": "https://github.com/default-fictional", "portfolio": "https://example.com/default-fictional"}
    settings = SimpleNamespace(**{scope["ENV_FIELDS"][k]: v for k, v in defaults.items()})
    for index, profile in enumerate(profiles):
        for group, resources in enumerate(groups):
            person = SimpleNamespace(**profile)
            items = [SimpleNamespace(**{**r, "id": UUID(r["id"])}) for r in resources]
            for request in requests:
                value = scope["direct"](SimpleNamespace(settings=settings), person, items, request)
                cases.append({"profile": index, "resources": group, "request": request.model_dump(mode="json"), "output": value})
    out = {"profiles": profiles, "resources": groups, "defaults": defaults, "cases": cases}
    encoded = json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/direct-answer-corpus.json"
    if args.check:
        if path.read_text() != encoded:
            raise SystemExit("direct_answer_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_direct_answer_cases:{len(cases)} bytes:{len(encoded.encode())}")


if __name__ == "__main__":
    main()
