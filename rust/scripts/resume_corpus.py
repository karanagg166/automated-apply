"""Fictional URL/resume/readiness oracle; AST-extract pure functions, never settings/ORM."""
import argparse
import ast
import hashlib
import ipaddress
import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from backend.app.ai.schemas import Contract
from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.candidate_profile import CandidateProfileCreate

ROOT = Path(__file__).resolve().parents[2]


def extract(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise ValueError("oracle_source_changed")
    exec(compile(ast.Module(body=selected, type_ignores=[]), path, "exec"), scope)


def safe_url(value):
    try:
        return str(TypeAdapter(PublicHTTPSURL).validate_python(value))
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = dict(Contract=Contract, UUID=UUID, Field=Field, Literal=Literal, hashlib=hashlib, json=json, safe_url=safe_url, BaseModel=BaseModel, re=re, CandidateProfileCreate=CandidateProfileCreate, OperationRejected=ValueError)
    extract("backend/app/schemas/applications.py", ["ResumeOption", "ResumeSelection"], scope)
    extract("backend/app/services/applications/resume_selector.py", ["digest", "private_resume_id", "select_resume"], scope)
    extract("backend/app/operations/onboarding.py", ["ProfileReadiness", "reject_placeholders", "assess_profile"], scope)
    urls = [None, "", "https://example.com", " https://example.com ", "HTTPS://EXAMPLE.COM:443", "https:example.com", "https://@example.com", "https://user:secret@example.com", "http://example.com", "ftp://example.com", "https://example.com:444", "https://localhost", "https://a.local", "https://a.localhost", "https://a.internal", "https://a.localdomain", "https://a.local.", "https://bücher.de/a b", "https://例え.テスト", "https://[::1]", "https://[2606:4700::1111]", "https://example.com/%0a", "https://example.com/%5c", "https://example.com/%250a", "https://example.com/%7f", "https://example.com/\tfoo", "https://example.com/\\path", "https://0x7f000001", "https://2130706433", "https://example.com/" + "é" * 700, " " * 2050 + "https://example.com", "https://example.com/" + "a" * 2028, "https://example.com/" + "a" * 2029]
    # Freeze Python 3.11 address classification, including CGNAT and boundary examples.
    networks = ipaddress.IPv4Address._constants._private_networks + [ipaddress.ip_network("100.64.0.0/10")]
    for net in networks:
        for number in [int(net.network_address) - 1, int(net.network_address), int(net.broadcast_address), int(net.broadcast_address) + 1]:
            if 0 <= number <= 2**32 - 1:
                urls.append("https://" + str(ipaddress.IPv4Address(number)))
    urls.extend("https://" + value for value in ["224.0.0.1", "8.8.8.8", "192.0.0.9", "192.0.0.10", "1.1.1.1"])
    url_cases = [{"input": value, "output": safe_url(value)} for value in urls]
    base = {"id": "10000000-0000-0000-0000-000000000001", "resource_type": "resume", "label": " Fictional résumé 🚀\n\"x\" ", "url": "https://example.com/resume.pdf", "user_confirmed": True, "is_primary": True, "source_type": "user", "updated_at": "2026-11-14T00:01:02.000007+00:00"}
    alternatives = [[], [base]]
    for key, values in {"label": ["éßİ\b\t\u001f\u007f", "😀"], "url": urls + ["private-resume:20000000-0000-0000-0000-000000000001", "private-resume:20000000000000000000000000000001", "private-resume:20000000-0000-0000-0000-00000000000A"], "source_type": ["private_upload", "environment_import"], "is_primary": [False], "user_confirmed": [False], "resource_type": ["other"], "updated_at": ["2026-11-14T00:01:02+00:00", "2026-11-14T05:31:02.123456+05:30"]}.items():
        for value in values:
            if key == "url" and value is None:
                continue
            item = {**base, key: value}
            alternatives.append([item])
            if key == "url" and str(value).startswith("private-resume:"):
                alternatives.append([{**item, "source_type": "private_upload"}])
    alternatives.extend([[base, {**base, "id": "10000000-0000-0000-0000-000000000002", "is_primary": primary, "user_confirmed": confirmed}] for primary in [True, False] for confirmed in [True, False]])
    selections = []
    for items in alternatives:
        resources = [SimpleNamespace(**{**item, "id": UUID(item["id"]), "updated_at": datetime.fromisoformat(item["updated_at"])}) for item in items]
        for selected in [None, base["id"], "10000000-0000-0000-0000-000000000099"]:
            output = scope["select_resume"](resources, UUID(selected) if selected else None).model_dump(mode="json")
            selections.append({"resources": items, "selected_id": selected, "output": output})
    minimal = {"full_name": "Fictional Person", "email": "fictional@example.com", "version": 4}
    ready = {**minimal, "verified_skills": ["Rust"], "verified_experience_years": 0, "projects": [{"name": "Sample", "description": "Confirmed implementation", "contribution": "Implemented coordinator", "technologies": ["Rust"]}], "preferences": {"target_titles": ["Engineer"], "remote_preference": "remote"}, "github_url": "https://github.com/fictional", "linkedin_url": "https://linkedin.com/in/fictional", "personal_website": "https://example.com"}
    readiness = []
    profiles = [None, minimal, ready, {**ready, "verified_experience_years": None}, {**ready, "projects": [{"name": "Sample", "description": "Evidence"}]}, {**ready, "github_url": "http://github.com/fictional"}, {**ready, "github_url": "https://github.com.evil.org/x"}, {**ready, "preferences": {}}, {**ready, "verified_skills": []}, {**ready, "personal_website": None}]
    for profile in profiles:
        for items in [[], [base], [{**base, "user_confirmed": False}], [{**base, "source_type": "private_upload", "url": "private-resume:20000000-0000-0000-0000-000000000001"}]]:
            for live in [False, True]:
                try:
                    output = scope["assess_profile"](SimpleNamespace(**profile) if profile else None, [SimpleNamespace(**{**item, "id": UUID(item["id"]), "updated_at": datetime.fromisoformat(item["updated_at"])}) for item in items], live=live).model_dump(mode="json")
                    result = {"output": output}
                except ValueError:
                    result = {"rejected": True}
                readiness.append({"profile": profile, "resources": items, "live": live, **result})
    result = {"urls": url_cases, "selections": selections, "readiness": readiness}
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/resume-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("resume_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_url_cases:{len(url_cases)} resume_cases:{len(selections)} readiness_cases:{len(readiness)}")


if __name__ == "__main__":
    main()
