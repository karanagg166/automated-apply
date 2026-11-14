"""Pure standard-library signature oracle, fictional keys and operation bodies only."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path

from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = dict(hashlib=hashlib, hmac=hmac)
    extract("backend/app/browser/owner_approval.py", ["approval_header"], scope)
    cases = []
    for key in ["fictional-owner-signing-key-0123456789", "é" * 32, "😀" * 32]:
        for path in ["/api/v1/application-answers/missing/00000000000000000000000000000001/approve", "/api/v1/application-answers/drafts/30000000-0000-0000-0000-000000000001/approve-reuse"]:
            for body in ['{"expected_version":1,"factual_confirmation":true}', '{ "expected_version": 1, "factual_confirmation": true }', '{"answer":"Fictional résumé 🚀"}']:
                nonce = "0123456789abcdef0123456789abcdef"
                timestamp = 1794700000
                header = scope["approval_header"](key, path, body.encode(), nonce=nonce, timestamp=timestamp)
                cases.append(dict(key=key, path=path, body=body, nonce=nonce, timestamp=timestamp, header=header))
    encoded = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    target = ROOT / "rust/agent-runtime/tests/fixtures/owner-proof-corpus.json"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("owner_proof_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_owner_proof_cases:{len(cases)}")


if __name__ == "__main__":
    main()
