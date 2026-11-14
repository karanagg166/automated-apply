"""Generate fictional PDF/parser, Fernet and import-suggestion compatibility evidence."""
import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from rust.scripts.question_corpus import constants
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def pdf(kind):
    writer = PdfWriter()
    count = {"no_pages": 0, "pages21": 21, "pages101": 101}.get(kind, 1)
    for _ in range(count):
        page = writer.add_blank_page(612, 792)
    if not count:
        page = None
    if kind == "text":
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 700 Td (Fictional Person) Tj 0 -18 Td (fictional@example.com) Tj 0 -18 Td (Python Rust PostgreSQL) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    if kind in {"uri", "launch", "javascript", "file_uri", "goto", "chained", "attachment"}:
        operation = "GoTo" if kind == "goto" else "Launch" if kind == "launch" else "JavaScript" if kind == "javascript" else "URI"
        action = DictionaryObject({NameObject("/S"): NameObject("/" + operation)})
        action[NameObject("/URI")] = TextStringObject("file:///fictional" if kind == "file_uri" else "https://example.com/fictional")
        if kind == "chained":
            action[NameObject("/Next")] = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("fictional")})
        annotation = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/FileAttachment" if kind == "attachment" else "/Link"), NameObject("/Rect"): ArrayObject([FloatObject(0)] * 4), NameObject("/A"): action})
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    if kind == "open_goto":
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/D"): ArrayObject([NumberObject(0), NameObject("/Fit")])})
    if kind == "open_array":
        writer._root_object[NameObject("/OpenAction")] = ArrayObject([NumberObject(0), NameObject("/Fit")])
    if kind == "root_aa":
        writer._root_object[NameObject("/AA")] = DictionaryObject({NameObject("/O"): DictionaryObject({NameObject("/S"): NameObject("/JavaScript")})})
    if kind == "page_aa":
        page[NameObject("/AA")] = DictionaryObject({NameObject("/O"): DictionaryObject({NameObject("/S"): NameObject("/JavaScript")})})
    if kind in {"embedded_names", "javascript_names"}:
        key = "/EmbeddedFiles" if kind == "embedded_names" else "/JavaScript"
        writer._root_object[NameObject("/Names")] = DictionaryObject({NameObject(key): DictionaryObject()})
    if kind in {"acroform", "xfa"}:
        form = DictionaryObject({NameObject("/Fields"): ArrayObject()})
        if kind == "xfa":
            form[NameObject("/XFA")] = TextStringObject("fictional")
        writer._root_object[NameObject("/AcroForm")] = form
    if kind in {"encrypted", "empty_password"}:
        writer.encrypt("" if kind == "empty_password" else "fictional-password")
    if kind == "stream_bomb":
        stream = DecodedStreamObject()
        stream.set_data(b" " * (4 * 1024 * 1024 + 1))
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    output = io.BytesIO()
    writer.write(output)
    raw = output.getvalue()
    if kind == "truncated":
        raw = raw[:100]
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cases = []
    for name in ["blank", "text", "uri", "launch", "javascript", "file_uri", "goto", "chained", "attachment", "open_goto", "open_array", "root_aa", "page_aa", "embedded_names", "javascript_names", "acroform", "xfa", "no_pages", "pages21", "pages101", "encrypted", "empty_password", "stream_bomb", "truncated"]:
        raw = pdf(name)
        result = {"name": name, "bytes": list(raw)}
        for mode, worker in [("extract", "backend/app/dashboard/resume_worker.py"), ("validate", "backend/app/candidate_context/pdf_worker.py")]:
            call = subprocess.run([sys.executable, str(ROOT / worker)], input=raw, capture_output=True, timeout=12, check=False)
            valid = call.returncode == 0 and (call.stdout == b"valid" if mode == "validate" else True)
            result[mode] = {"accepted": valid}
            if valid and mode == "extract":
                value = json.loads(call.stdout)
                result[mode].update(pages=value["pages"], links=value["links"], words=value["text"].split())
        cases.append(result)
    scope = {"re": __import__("re")}
    constants("backend/app/dashboard/resumes.py", {"SKILLS"}, scope)
    extract("backend/app/dashboard/resumes.py", ["suggestions"], scope)
    texts = ["", "Fictional Person\nfictional@example.com\nPython PostgreSQL", "1234\nFictional Person\nReact Next.js C++", "0\n1\n2\nHidden Name", "Fictional Person\u001cPython\u0085Redis", "Pythonic Reactivity Node.js Docker GitHub SQL", "Python\u0301 _Python aPython Python² Python٣", "ſQL GİT PyThOn", "FIRST.LAST+fictional@example.co.uk", "Résumé\nFictional Person\nPython"]
    suggestions = [{"text": text, "output": scope["suggestions"](text)} for text in texts]
    key = base64.urlsafe_b64encode(bytes(range(32)))
    cipher = Fernet(key)
    tokens = []
    for raw in [b"%PDF-fictional\n%%EOF", pdf("text")]:
        token = cipher._encrypt_from_parts(raw, 1600000000, bytes(range(16)))
        tokens.append({"raw": list(raw), "token": token.decode(), "sha256": hashlib.sha256(raw).hexdigest()})
    result = {"pdfs": cases, "suggestions": suggestions, "fernet": {"key": key.decode(), "cases": tokens}}
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = ROOT / "rust/document-worker/tests/fixtures/pdf-corpus.json"
    if args.check:
        if path.read_text() != encoded:
            raise SystemExit("pdf_corpus_drift")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded)
    print(f"fictional_pdf_cases:{len(cases)} suggestions:{len(suggestions)} fernet:{len(tokens)} bytes:{len(encoded.encode())}")


if __name__ == "__main__":
    main()
