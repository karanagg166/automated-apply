"""Bound and validate the actual outgoing multipart body against the reviewed digest."""

import hashlib
from email import policy
from email.parser import BytesParser

from backend.app.services.applications.resume_selector import digest


def reviewed_multipart(raw, content_type, attempt_id, expected_digest):
    if (
        not raw
        or len(raw) > 6 * 1024 * 1024
        or not content_type.startswith("multipart/form-data;")
    ):
        return False
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + raw
    )
    entries, reserved = [], {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        value, filename = part.get_payload(decode=True), part.get_filename()
        if name in {"_aa_attempt_id", "_aa_payload_digest"}:
            if name in reserved:
                return False
            reserved[name] = value.decode()
        elif filename is not None:
            entries.append(
                [
                    name,
                    {
                        "name": filename,
                        "sha256": hashlib.sha256(value).hexdigest(),
                        "size": len(value),
                    },
                ]
            )
        else:
            entries.append([name, value.decode()])
        if len(entries) > 100:
            return False
    return (
        reserved.get("_aa_attempt_id") == str(attempt_id)
        and reserved.get("_aa_payload_digest") == expected_digest
        and digest(entries) == expected_digest
    )
