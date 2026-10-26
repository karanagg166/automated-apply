"""Disposable structural PDF validator. Never extracts or prints resume contents."""

import io
import sys

MAX_BYTES = 5 * 1024 * 1024


def valid_pdf(raw: bytes) -> bool:
    if (
        not raw.startswith(b"%PDF-")
        or len(raw) > MAX_BYTES
        or b"%%EOF" not in raw[-1024:]
    ):
        return False
    from pypdf import PdfReader
    from pypdf.generic import DictionaryObject

    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
            return False
        root = reader.trailer["/Root"]
        if not isinstance(root, DictionaryObject):
            return False
        if any(key in root for key in ("/OpenAction", "/AA")):
            return False
        names = root.get("/Names")
        if names and any(
            key in names.get_object() for key in ("/JavaScript", "/EmbeddedFiles")
        ):
            return False
        form = root.get("/AcroForm")
        if form and "/XFA" in form.get_object():
            return False
        for page in reader.pages:
            if "/AA" in page:
                return False
            for annotation in page.get("/Annots", []):
                item = annotation.get_object()
                if "/AA" in item:
                    return False
                action = item.get("/A")
                if action and action.get_object().get("/S") not in {"/URI", "/GoTo"}:
                    return False
        return True
    except Exception:
        return False


def main() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    sys.stdout.write("valid" if valid_pdf(raw) else "invalid")


if __name__ == "__main__":
    main()
