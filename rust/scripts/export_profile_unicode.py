"""Pin Python 3.11's public Unicode 14 category/digit semantics; no user data."""
import argparse
import json
import unicodedata
from pathlib import Path

from idna import idnadata

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    if unicodedata.unidata_version != "14.0.0":
        raise SystemExit("unicode_14_required")
    excluded, ranges, digits = [], [], {}
    for code in range(0x110000):
        char = chr(code)
        if unicodedata.category(char)[0] not in "LNPSM":
            excluded.append(code)
        if char.isdecimal() and not char.isascii():
            digits[char] = str(unicodedata.decimal(char))
    for code in excluded:
        if ranges and ranges[-1][1] + 1 == code:
            ranges[-1][1] = code
        else:
            ranges.append([code, code])
    words = []
    for code in range(0x110000):
        if chr(code).isalnum() or code == 95:
            if words and words[-1][1] + 1 == code:
                words[-1][1] = code
            else:
                words.append([code, code])
    pvalid = [[item >> 32, (item & 0xFFFFFFFF) - 1] for item in idnadata.codepoint_classes["PVALID"]]
    value = {"unicode": "14.0.0", "idna_version": idnadata.__version__, "idna_pvalid": pvalid, "unsafe_ranges": ranges, "word_ranges": words, "decimal_digits": digits}
    path = ROOT / "rust/agent-runtime/schemas/profile-unicode.json"
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("profile_unicode_drift")
    else:
        path.write_text(encoded)
    print("profile_unicode_matches" if check else "profile_unicode_exported")


if __name__ == "__main__":
    main()
