"""Bounded local PDF extraction in a disposable subprocess. No network/model calls."""

import io
import json
import resource
import sys

from pypdf import PdfReader


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    # Linux enforces address space. macOS is supervised by the parent RSS watcher.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    raw = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
        raise ValueError("invalid_pdf")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) > 20:
        raise ValueError("encrypted_or_too_many_pages")
    root = reader.trailer["/Root"]
    if (
        root.get("/OpenAction")
        or root.get("/AA")
        or "/JavaScript" in root.get("/Names", {})
        or reader.attachments
    ):
        raise ValueError("active_content_not_supported")
    parts = []
    for page in reader.pages:
        if len(page.get_contents().get_data()) > 4 * 1024 * 1024:
            raise ValueError("page_too_complex")
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A", {})
            if action and action.get("/S") not in (None, "/URI", "/GoTo"):
                raise ValueError("active_content_not_supported")
        parts.append((page.extract_text() or "")[:16000])
    print(json.dumps({"text": "\n".join(parts)[:32000], "pages": len(reader.pages)}))


if __name__ == "__main__":
    main()
