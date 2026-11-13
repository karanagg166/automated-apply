"""Freeze public HTML5 decoding tables for Python-to-Rust matching compatibility."""
import argparse
import html
import json
import sys
import unicodedata
from pathlib import Path


def main():
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("python311_reference_required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "domain/data"
    values = {
        "reference.json": {"reference": "Python 3.11 standard library", "unicode_version": unicodedata.unidata_version},
        "html5.json": html.entities.html5,
        "unicode_fold.json": {chr(i): chr(i).casefold() for i in range(128, 0x110000) if chr(i).casefold() != chr(i)},
        "unicode_lower.json": {chr(i): chr(i).lower() for i in range(128, 0x110000) if chr(i).lower() != chr(i)},
        "html_numeric.json": {str(k): v for k, v in html._invalid_charrefs.items()},
        "html_invalid.json": sorted(html._invalid_codepoints),
    }
    for name, value in values.items():
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        path = root / name
        if args.check:
            if path.read_text() != text:
                raise SystemExit("html_contract_drift")
        else:
            path.write_text(text)
    print("html_contract_current")


if __name__ == "__main__":
    main()
