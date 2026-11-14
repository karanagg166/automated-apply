"""Pure AST retrieval oracle with fictional facts; never settings/ORM/provider imports."""
import argparse
import ast
import json
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from backend.app.ai.schemas import EvidenceReference
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    path = "backend/app/services/candidate_evidence_retrieval.py"
    scope = dict(re=re, json=json, EvidenceReference=EvidenceReference)
    tree = ast.parse((ROOT / path).read_text())
    constants = [node for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "STOPWORDS"]
    exec(compile(ast.Module(body=constants, type_ignores=[]), path, "exec"), scope)
    extract(path, ["tokens", "retrieve"], scope)
    project = {"name": "Rust queue", "description": "A durable job queue", "purpose": "Preserve work", "contribution": "I implemented Rust workers and REST APIs.", "technologies": ["Rust", "PostgreSQL"], "engineering_challenges": "A race caused duplicate claims.", "solutions": "I added version checks and locks."}
    profile = {"id": "10000000-0000-0000-0000-000000000001", "projects": [project, {**project, "name": "Python service", "contribution": "I built Python APIs.", "technologies": ["Python"]}], "verified_roles": [{"company": "Fictional Employer", "role": "Engineer", "highlight": "I developed Java and Rust APIs."}], "verified_skills": ["Rust", "Python", "Java"], "preferences": {"target_titles": ["Engineer"], "technology_stacks": ["Rust"], "prioritize_startups": False, "minimum_salary": 999, "current_compensation": {"amount": "100", "currency": "INR"}}, "summary": "I built reliable Rust services.", "education": [{"institution": "Fictional School", "qualification": "Degree", "graduation_year": 2020}], "certifications": []}
    profiles = [profile]
    for changes in [{"projects": []}, {"verified_skills": ["TypeScript"]}, {"verified_skills": ["Straße", "résumé", "C++", "C#"]}, {"projects": [{**project, "contribution": None}]}, {"projects": [{**project, "engineering_challenges": None}]}, {"projects": [{**project, "solutions": None}]}, {"projects": [{**project, "name": "Système", "contribution": "I built résumé Straße C++ C# handlers.\nI wrote quoted \"APIs\"."}]}, {"preferences": {"target_titles": [], "prioritize_startups": False}}, {"projects": [{**project, "name": "same"} for _ in range(9)]}]:
        profiles.append({**deepcopy(profile), **changes})
    evidence = [{"id": f"20000000-0000-0000-0000-{i:012d}", "title": "Fictional source", "content": content, "user_confirmed": confirmed, "project": details} for i, (content, confirmed, details) in enumerate([("I implemented Rust APIs.", True, None), ("We built Python APIs.", True, None), ("I built Java services.", False, None), ("I built a project.", True, project), ("I developed TypeScript work.", True, {**project, "contribution": "I developed TypeScript workers.", "technologies": ["TypeScript"]}), ("I  built Rust services.", True, None), ("I designed Rust APIs.", True, None), ("İ implemented Rust workers.", True, None)], 1)]
    evidence_sets = [[], evidence, [{**item, "user_confirmed": False} for item in evidence]]
    questions = ["Describe a project", "Describe Rust queue", "Describe Python service", "Your most challenging project", "What problem did you solve?", "Explain bug", "Explain bugs²", "Explain bugs_", "Explain debug²", "debugging", "Failure", "faılure", "Explain Rust experience", "Experience with Rust", "Experience using TypeScript", "Experience in Rust and Python", "Worked with Java", "Experience with résumé", "Experience with RİST", "Experience with\nRust", "Experience with\u001cRust", "Describe C++ and C#", "Describe Straße", "Describe Système", "What motivates you?", "Why join a startup?", "Introduce yourself", "Rust\nworkers", "No facts supplied"]
    cases = []
    for pindex, body in enumerate(profiles):
        candidate = SimpleNamespace(**{**body, "id": UUID(body["id"])})
        for eindex, entries in enumerate(evidence_sets):
            items = [SimpleNamespace(**{**item, "id": UUID(item["id"])}) for item in entries]
            for category in ["project_explanation", "technical_experience", "motivation", "startup_interest", "short_text", "unknown"]:
                selected = questions if category in {"project_explanation", "technical_experience"} else questions[-5:]
                for question in selected:
                    cases.append({"profile": pindex, "evidence": eindex, "question": question, "category": category, "output": scope["retrieve"](candidate, items, question, category)})
    result = {"profiles": profiles, "evidence_sets": evidence_sets, "cases": cases}
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    target = ROOT / "rust/agent-runtime/tests/fixtures/evidence-corpus.json"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("evidence_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_evidence_cases:{len(cases)}")


if __name__ == "__main__":
    main()
