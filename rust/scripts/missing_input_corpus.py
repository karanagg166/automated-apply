"""AST-only missing-fact DTO, identity and sensitive-retention oracle; fictional data."""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from backend.app.ai.schemas import Contract, GenerateRequest

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    path = "backend/app/knowledge/missing_input.py"
    tree = ast.parse((ROOT / path).read_text())
    names = {"permitted", "key_for", "MissingInputCreate", "MissingInputEdit", "MissingInputApprove"}
    nodes = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in {"PREFIX", "SENSITIVE"} or isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    scope = dict(re=re, hashlib=hashlib, UUID=UUID, Literal=Literal, Field=Field, StrictBool=StrictBool, model_validator=model_validator, Contract=Contract, GenerateRequest=GenerateRequest, ProfileConflictError=ValueError)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), scope)
    base = dict(question="Describe your experience", missing_fact="Your confirmed contribution")
    edit = dict(expected_version=1, answer="I built fictional workers.", evidence_note="Owner's fictional confirmation")
    approve = dict(expected_version=1, expected_profile_version=4, factual_confirmation=True)
    inputs = {"create": [base], "edit": [edit], "approve": [approve]}
    for name, source in [("create", base), ("edit", edit), ("approve", approve)]:
        for field in source:
            for value in [None, True, False, 1, 1.0, 1.5, " ", "\u001cSaved fact\u001f", " Saved fact ", "true", "1", "1.0", "1_000", "9007199254740993", 9007199254740993, "18446744073709551615", "\u001c1\u001f"]:
                inputs[name].append({**source, field: value})
        inputs[name].append({**source, "owner_approved": True})
        inputs[name].append({})
    for field, values in dict(packet_id=[None, "bad", "10000000-0000-0000-0000-000000000001", "{10000000000000000000000000000001}"], reason=[None, "", " Reason ", "x" * 2001], required_input_type=["text", "number", "choice", "evidence", "profile_edit", " evidence ", "unknown"], question=["", "x" * 2001], missing_fact=["x" * 2001], save_draft=[True, "yes"], max_words=[0, 1, 1501]).items():
        for value in values:
            inputs["create"].append({**base, field: value})
    for field, values in dict(answer=["x" * 10000, "x" * 10001], evidence_note=["", "x" * 2000, "x" * 2001], expected_version=[0, -1, "1e0", "+-1", "1__2", "1.0_0"]).items():
        for value in values:
            inputs["edit"].append({**edit, field: value})
    contracts = []
    for kind, values in inputs.items():
        model = scope[{"create": "MissingInputCreate", "edit": "MissingInputEdit", "approve": "MissingInputApprove"}[kind]]
        for value in values:
            try:
                result = dict(accepted=True, output=model.model_validate(value).model_dump(mode="json"))
            except ValueError:
                result = dict(accepted=False)
            contracts.append(dict(kind=kind, input=value, **result))
    questions = ["What is your password?", "OTP", "What is your CVV?", "Terms and conditions", "Disability", "Your religion?", "Your approved contribution?", "What is your work authorization?", "What is your compensation?", "What passport?", "A\u001cverification code", "²OTP", "\U00011f02OTP", "one\n time code", "gender identity", "consent", "What APIs?", "passſword"]
    answers = ["I built fictional workers.", "password: secret", "API_key is fictional", "access-token=fictional", "OTP is 123", "-----BEGIN RSA PRIVATE KEY-----", "otp² is 123", "\U00011f02otp=123", "password\u001cis secret", "password\nis secret", "I used tokenization."]
    retention = []
    for question in questions:
        for answer in answers:
            try:
                scope["permitted"](question, answer)
                accepted = True
            except ValueError:
                accepted = False
            retention.append(dict(question=question, answer=answer, accepted=accepted))
    profile = "10000000-0000-0000-0000-000000000001"
    keys = []
    for question in ["Your contribution?", " YOUR CONTRIBUTION? ", "\u001cYour contribution?\u001f", "Straße?", "STRASSE?", "İ?", "I\u0307?", "A|B", "Résumé 🚀"]:
        for job_id in [None, "20000000-0000-0000-0000-000000000001"]:
            for packet_id in [None, "30000000-0000-0000-0000-000000000001"]:
                for company_name, job_description in [(None, None), ("None", "None"), ("Fictional Labs", "A fictional role"), ("A|B", "C"), ("A", "B|C")]:
                    key = scope["key_for"](profile, question, job_id, packet_id, company_name, job_description)
                    keys.append(dict(profile_id=profile, question=question, job_id=job_id, packet_id=packet_id, company_name=company_name, job_description=job_description, key=key))
    encoded = json.dumps(dict(contracts=contracts, retention=retention, keys=keys), indent=2, ensure_ascii=False) + "\n"
    target = ROOT / "rust/agent-runtime/tests/fixtures/missing-input-corpus.json"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("missing_input_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_missing_contracts:{len(contracts)} sensitive_checks:{len(retention)} identities:{len(keys)}")


if __name__ == "__main__":
    main()
