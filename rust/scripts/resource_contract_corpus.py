"""Public resource/evidence DTO oracle only; no settings, ORM or candidate data."""
import argparse
import json
from pathlib import Path

from backend.app.schemas.candidate_resources import (
    EvidencePatch,
    EvidenceWrite,
    ResourceWrite,
)

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    models = {"resource": ResourceWrite, "evidence": EvidenceWrite, "patch": EvidencePatch}
    base = {"resource": {"resource_type": "resume", "label": " Fictional   resume ", "url": "https://example.com"}, "evidence": {"evidence_type": "project", "title": " Fictional   project ", "content": " One   two\nthree "}, "patch": {"title": " Correction "}}
    cases = []
    values = [None, True, False, 0, 1, 1.0, 1.5, "", "  ", " true ", "true", "no", "1_0", "1.0", [], {}, " a   b "]
    for operation, model in models.items():
        inputs = [base[operation], {}, {**base[operation], "unknown": True}]
        for key in model.model_fields:
            inputs.extend({**base[operation], key: value} for value in values)
        for key in ["label", "title", "content", "source_description"]:
            if key in model.model_fields:
                inputs.extend({**base[operation], key: value} for value in [" x\u001cy ", "a" * 200, "a" * 201, "é" * 4000, "a" * 4001])
        if "project" in model.model_fields:
            inputs.extend({**base[operation], "project": project} for project in [{"name": " A   B ", "technologies": ["Rust", "RUST"]}, {"name": "P", "url": "http://example.com"}, {"name": "P", "url": "https://127.0.0.1"}, {"name": "P", "url": "https://example.com"}, {"name": "P", "achievements": [" x   y "]}, {"name": "P", "injected": True}])
        if operation == "evidence":
            inputs.extend({**base[operation], "evidence_type": kind, "project": {"name": "P"}} for kind in ["project", "other", "experience"])
        if operation == "resource":
            inputs.extend({**base[operation], "id": value} for value in ["10000000000000000000000000000001", "{10000000-0000-0000-0000-000000000001}", "urn:uuid:10000000-0000-0000-0000-000000000001"])
            inputs.extend({**base[operation], "expected_profile_version": value} for value in [2147483647, 2147483648, "001", "+1", "1e2", -1, 0, " 1 ", "1_0.00"])
        for key, kinds in {"resource_type": ["resume", "github", "linkedin", "portfolio", "other", " RESUME ", " resume "], "source_type": ["user", "environment_import", "private_upload", " user "], "evidence_type": ["project", "experience", "achievement", "resume_note", "other", " project "]}.items():
            if key in model.model_fields:
                inputs.extend({**base[operation], key: kind} for kind in kinds)
        for data in inputs:
            try:
                value = model.model_validate(data).model_dump(mode="json", exclude_unset=operation == "patch")
                result = {"accepted": True, "value": value}
            except ValueError:
                result = {"accepted": False}
            cases.append({"operation": operation, "input": data, **result})
    encoded = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/resource-contract-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("resource_contract_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_resource_contract_cases:{len(cases)}")


if __name__ == "__main__":
    main()
