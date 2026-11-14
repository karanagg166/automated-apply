"""Fictional fixed-English safeguard regex oracle using Python Unicode 14."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    patterns = {"person": (r"\b(?:I|my)\b", re.I), "number": (r"\b\d[\d,.]*(?:%|[kKmMbB])?\b", 0), "name": (r"\b[A-Z][A-Za-z0-9+#]*(?:[.][A-Za-z]+)?\b", 0), "sentence": (r"(?<=[.!?])\s+|\n", 0), "work": (r"\bI (?:built|implemented|worked|developed|designed)\b", re.I), "challenge": (r"\b(?:challeng\w*|bugs?|failure)\b", re.I)}
    texts = ["I built Rust APIs.", "My project uses C++ and C#.", "I built Node.js workers.", "I built 10% more 1,000 APIs.", "We built Python.", "İ implemented Rust.", "ı built Java.", "I\u00a0built Rust.", "I  built Rust.", "I built ١٢ APIs.", "Rust١ APIs", "I built 1,000a users.", "I fixed bugs².", "I fixed bugs_", "faılure", "challenging\u11f02 bugs", "One sentence.\u001cSecond sentence!\nThird."]
    for char in ["a", "_", "²", "Ⅰ", "é", "ß", "ſ", "K", "İ", "ı", "λ", "١", "\u0301", "\u203f", "\U00011f02", "\U00011f50", "😀", "\u001c", "\u001f", "\u00a0", "\u2028", "\u202f"]:
        texts.extend([f"{char}I built Rust{char}.", f"I{char}built Rust.", f"I built 10{char} users.", f"I fixed bugs{char}.", f"I built Rust.\n{char}My work!{char}More."])
    cases = [{"pattern": name, "text": text, "insensitive": bool(flags), "output": re.findall(pattern, text, flags)} for name, (pattern, flags) in patterns.items() for text in texts]
    encoded = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "rust/agent-runtime/tests/fixtures/guard-regex-corpus.json"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("guard_regex_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_guard_regex_cases:{len(cases)}")


if __name__ == "__main__":
    main()
