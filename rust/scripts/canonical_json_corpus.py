"""Stable Python JSON/hash oracle over fictional Unicode, finite doubles and bounded integers."""
import argparse
import hashlib
import json
import math
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    values = [None, True, False, 0, -1, 2**63 - 1, -(2**63), 2**64 - 1, 0.0, -0.0, 1.0, -1.0, 0.1, 1e-4, 1e-5, 1e15, 1e16, 1e17, 1.2345678901234567, 5e-324, 1.7976931348623157e308, "éßİ\u007f\u001c😀", {"z": 1, "a": ["résumé", "🚀", True, 0.0, 1e-8]}, {"é": "accent", "a": "ASCII", "😀": "supplementary", "𝄞": "music"}]
    rng = random.Random(718035)
    for _ in range(2000):
        number = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
        if math.isfinite(number):
            values.append(number)
    cases = []
    for value in values:
        compact = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        cases.append({"input": value, "compact": compact, "spaced": json.dumps(value, ensure_ascii=True, sort_keys=True), "utf8": json.dumps(value, ensure_ascii=False, sort_keys=True), "sha256": hashlib.sha256(compact.encode()).hexdigest()})
    encoded = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/canonical-json-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("canonical_json_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_canonical_json_cases:{len(cases)}")


if __name__ == "__main__":
    main()
