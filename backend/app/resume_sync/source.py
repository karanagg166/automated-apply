"""Strict source identity; supplied URLs are never used as download destinations."""

import re
from urllib.parse import parse_qs, urlsplit

FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def canonical_source(value: str, expected_file_id: str | None = None) -> tuple[str, str]:
    try:
        url = urlsplit(value)
        match = re.fullmatch(r"/file/d/([A-Za-z0-9_-]{10,200})/view", url.path)
        query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
        valid = (
            len(value) <= 2048 and value.isascii()
            and url.scheme == "https" and url.netloc == "drive.google.com"
            and not url.fragment and match
            and set(query) <= {"usp"} and len(query.get("usp", [])) <= 1
            and not any(ord(c) <= 32 for c in value)
        )
        if not valid:
            raise ValueError
        file_id = match.group(1)
        if expected_file_id is not None and file_id != expected_file_id:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("Use the exact Google Drive /file/d/FILE_ID/view URL with a matching file ID") from None
    return file_id, f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
