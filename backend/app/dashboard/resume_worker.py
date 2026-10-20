"""Bounded local PDF extraction in a disposable subprocess. No network/model calls."""

import io
import json
import resource
import sys

from pypdf import PdfReader
from pypdf.generic import ArrayObject


def resolved(value):
    return value.get_object() if hasattr(value, "get_object") else value


def safe_action(value, *, opening=False):
    action = resolved(value)
    # A local /GoTo destination (common in LaTeX PDFs) only selects the initial
    # page/view. It has no executable or external action. Chained actions fail closed.
    if opening and isinstance(action, ArrayObject):
        return True
    return isinstance(action, dict) and not action.get("/Next") and action.get("/S") in (
        {"/GoTo"} if opening else {"/URI", "/GoTo"}
    )


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    # Linux enforces address space. macOS is supervised by the parent RSS watcher.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    raw = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
        raise ValueError("invalid_pdf")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError("encrypted_or_too_many_pages")
    root = reader.trailer["/Root"]
    names = resolved(root.get("/Names", {}))
    if (
        (root.get("/OpenAction") and not safe_action(root["/OpenAction"], opening=True))
        or root.get("/AA")
        or "/JavaScript" in names
        or reader.attachments
        or root.get("/AcroForm")
    ):
        raise ValueError("active_content_not_supported")
    parts, links = [], []
    for page in reader.pages:
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 4 * 1024 * 1024:
            raise ValueError("page_too_complex")
        if page.get("/AA"):
            raise ValueError("active_content_not_supported")
        for annotation in page.get("/Annots", []):
            obj = annotation.get_object()
            if obj.get("/AA") or obj.get("/Subtype") in {"/FileAttachment", "/RichMedia", "/Movie", "/Sound", "/Screen", "/3D", "/Widget"}:
                raise ValueError("active_content_not_supported")
            action = obj.get("/A", {})
            action = resolved(action)
            if action and not safe_action(action):
                raise ValueError("active_content_not_supported")
            uri = str(action.get("/URI", "")) if action else ""
            if uri and not uri.lower().startswith(("https://", "http://", "mailto:", "tel:")):
                raise ValueError("active_content_not_supported")
            if uri.startswith("https://") and len(uri) <= 2048 and len(links) < 100:
                links.append(uri)
        parts.append((page.extract_text() or "")[:16000])
    print(json.dumps({"text": "\n".join(parts)[:32000], "pages": len(reader.pages), "links": sorted(set(links))}))


if __name__ == "__main__":
    main()
