"""Execute original fingerprint expressions against fictional, injected snapshot material."""
import argparse
import ast
import asyncio
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from backend.app.ai.schemas import GenerateRequest
from backend.app.candidate_context.persistence import MemoryRecordStore
from backend.app.candidate_context.service import CandidateContextService
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from rust.scripts.question_corpus import classifier_oracle
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def method(path, class_name, name, target, scope, allowed):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.name = target

    class StripKnownImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module not in allowed:
                raise ValueError("unexpected_fingerprint_oracle_import")
            return None

    module = StripKnownImports().visit(ast.Module(body=[node], type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)


async def build():
    scope, _ = classifier_oracle()
    scope.update(json=json, hashlib=hashlib, CandidateProfileCreate=CandidateProfileCreate)
    extract("backend/app/services/applications/resume_selector.py", ["digest"], scope)
    method("backend/app/services/application_answer_service.py", "ApplicationAnswerService", "_generation_stamp", "source_generation", scope, {"backend.app.candidate_context.runtime", "backend.app.knowledge.reuse", "backend.app.schemas.candidate_profile", "backend.app.services.applications.resume_selector"})
    method("backend/app/knowledge/missing_input.py", "MissingInputService", "stamp", "source_missing", scope, {"backend.app.services.application_answer_service", "backend.app.services.applications.resume_selector"})
    reuse = ast.parse((ROOT / "backend/app/knowledge/reuse.py").read_text())
    evidence = next(n for n in reuse.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "evidence_digest")
    evidence_return = compile(ast.Expression(evidence.body[-1].value), "evidence_digest_return", "eval")

    async def evidence_digest(session, profile):
        rows = [SimpleNamespace(**{**r, "id": UUID(r["id"])}) for r in session.evidence if r["candidate_profile_id"] == str(profile.id)]
        rows.sort(key=lambda r: str(r.id))
        return eval(evidence_return, scope, dict(rows=rows, profile=profile))

    async def approved(session, question, category):
        return await CandidateContextService(MemoryRecordStore(session.projects)).answer_evidence(question, category)

    async def job_digest(session, job_id):
        return session.job_digest if job_id else None

    scope.update(evidence_digest=evidence_digest, approved_answer_evidence=approved, job_digest=job_digest)
    scope["ApplicationAnswerService"] = lambda session: SimpleNamespace(_generation_stamp=lambda req: scope["source_generation"](session.service, req))
    profile_id = "00000000-0000-0000-0000-000000000002"
    base = dict(full_name="Fictional Person", email="fictional@example.com", id=profile_id, version=4)
    profiles = [base, {**base, "full_name": " Changed Fictional Name "}, {**base, "preferences": {"current_compensation": {"amount": "123456.75", "currency": "INR", "period": "year", "kind": "ctc"}}}, {**base, "verified_skills": ["Rust", "Straße"], "summary": "\u001cFictional résumé 🚀\u001f"}]
    owned = dict(id="40000000-0000-0000-0000-000000000001", candidate_profile_id=profile_id, title="Queue", content="I built Rust workers.", project=None, user_confirmed=True)
    unconfirmed = {**owned, "id": "40000000-0000-0000-0000-000000000002", "title": "Unconfirmed", "content": "Fictional unconfirmed fact.", "user_confirmed": False}
    foreign = {**owned, "id": "40000000-0000-0000-0000-000000000003", "candidate_profile_id": "00000000-0000-0000-0000-000000000099"}
    inventories = [[], [owned, unconfirmed, foreign], [{**owned, "content": "I built changed Rust workers."}, unconfirmed, foreign], [owned, {**unconfirmed, "user_confirmed": True}, foreign]]
    projects = [{}, json.loads((ROOT / "rust/agent-runtime/tests/fixtures/project-context-corpus.json").read_text())["records"][0]]
    jobs = [None, *json.loads((ROOT / "rust/agent-runtime/tests/fixtures/job-context-corpus.json").read_text())["listings"][:2]]
    cases = []
    for p, raw in enumerate(profiles):
        for e, inventory in enumerate(inventories):
            for k, project in enumerate(projects):
                for j, job in enumerate(jobs):
                    session = SimpleNamespace(evidence=inventory, projects=project, job_digest=job["job_digest"] if job else None)

                    async def profile(raw=raw):
                        return SimpleNamespace(**{**deepcopy(raw), "id": UUID(raw["id"])})

                    session.service = SimpleNamespace(repo=SimpleNamespace(profile=profile, session=session))
                    missing = SimpleNamespace(session=session)
                    for question in ["Describe a project", "experience with Rust", "Email", "Introduce yourself", "Why this company?"]:
                        request = GenerateRequest(question=question, job_id=job["job"]["id"] if job else None)
                        generation = await scope["source_generation"](session.service, request)
                        stamp = await scope["source_missing"](missing, request)
                        cases.append(dict(profile=p, evidence=e, projects=k, job=j, request=request.model_dump(mode="json"), generation=generation, missing=stamp))
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("fingerprint_oracle_loaded_runtime")
    return dict(profiles=profiles, evidence=inventories, projects=projects, jobs=jobs, cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    corpus = asyncio.run(build())
    target = ROOT / "rust/agent-runtime/tests/fixtures/answer-context-corpus.json"
    encoded = json.dumps(corpus, indent=2, ensure_ascii=False) + "\n"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("answer_context_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_answer_fingerprints:{len(corpus['cases'])}")


if __name__ == "__main__":
    main()
